"""Delivery must retain G0/score evidence and reject evidence for another CSV."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_final_bundle import seal_bundle, sha, supporting_files


class FinalBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'input'
        self.root.mkdir()
        self.model = hashlib.sha256(b'synthetic-model').hexdigest()
        self.write('demo-handoff.zip', b'synthetic-handoff')
        self.write('ds-candidate.csv', b'synthetic-csv')
        self.write('sources.zip', b'synthetic-source')
        self.write('local-acceptance.json', b'{}')
        self.write('evidence/score/screen.png', b'synthetic-image')
        with zipfile.ZipFile(self.root/'g0-b2.zip', 'w') as archive:
            for name, content in {'bundle-manifest.json': b'{}', 'model/model.joblib': b'synthetic-model',
                                  'champion.csv': b'synthetic-csv', 'handoff-b2.zip': b'synthetic-handoff'}.items():
                archive.writestr('fixture/'+name, content)
        self.evidence = {'screenshot_file': 'screen.png',
            'screenshot_sha256': sha(self.root/'evidence/score/screen.png'),
            'csv_sha256': sha(self.root/'ds-candidate.csv'),
            'file_binding_accepted': True, 'displayed_score': 0.8}
        self.write('evidence/score/score.json', json.dumps(self.evidence).encode())
        self.write('release-manifest.json', json.dumps({'demo': {'model_sha256': self.model},
            'g0': {'archive_sha256': sha(self.root/'g0-b2.zip')},
            'competition': {'score_evidence': 'evidence/score/score.json', 'reported_score': 0.8}}).encode())
        self.checksums()

    def write(self, name, data):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def checksums(self):
        (self.root/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(self.root).as_posix()}\n'
            for p in sorted(self.root.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))

    def validate(self):
        return supporting_files(self.root, self.root/'demo-handoff.zip', self.root/'ds-candidate.csv', self.model)

    def test_complete_evidence_and_recursive_portable_archive(self):
        files, manifest = self.validate()
        self.assertIn('g0-b2.zip', files)
        self.assertEqual(manifest['competition']['reported_score'], 0.8)
        archive = seal_bundle(self.root)
        with zipfile.ZipFile(archive) as bundle:
            for line in bundle.read('tramflow-local-final/SHA256SUMS').decode().splitlines():
                digest, name = line.split('  ', 1)
                self.assertEqual(hashlib.sha256(bundle.read('tramflow-local-final/'+name)).hexdigest(), digest)
            self.assertIn('tramflow-local-final/evidence/score/screen.png', bundle.namelist())
        before = archive.read_bytes()
        with self.assertRaises(FileExistsError):
            seal_bundle(self.root)
        self.assertEqual(archive.read_bytes(), before)

    def test_altered_screenshot_is_not_accepted(self):
        self.write('evidence/score/screen.png', b'changed')
        with self.assertRaises(ValueError):
            self.validate()
        self.checksums()
        with self.assertRaisesRegex(ValueError, 'Score evidence'):
            self.validate()

    def test_score_for_other_csv_or_unaccepted_claim_is_rejected(self):
        for update in [{'csv_sha256': '0'*64}, {'file_binding_accepted': False},
                       {'screenshot_file': '../screen.png'}, {'displayed_score': True}]:
            with self.subTest(update=update):
                self.write('evidence/score/score.json', json.dumps(self.evidence | update).encode())
                self.checksums()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_wrong_model_or_missing_G0_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'different model'):
            supporting_files(self.root, self.root/'demo-handoff.zip', self.root/'ds-candidate.csv', '0'*64)
        (self.root/'g0-b2.zip').unlink()
        self.checksums()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.validate()

    def test_checksum_cannot_escape_root_or_copy_a_symlink(self):
        external = self.root.parent/'outside.txt'
        external.write_text('outside')
        (self.root/'SHA256SUMS').write_text(f'{sha(external)}  ../outside.txt\n')
        with self.assertRaisesRegex(ValueError, 'Invalid supporting'):
            self.validate()
        (self.root/'alias.txt').symlink_to(external)
        self.checksums()
        with self.assertRaisesRegex(ValueError, 'Invalid supporting'):
            self.validate()
