import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_final_bundle import additional_evidence, accept_runtime, bundle_readme, runtime_hashes, sha


class ClosureEvidenceTests(unittest.TestCase):
    def test_bundle_root_guide_links_to_extracted_sources(self):
        text = ('[status](final-closure-status.md#checks) [model](../../ml/README.md) '
                '[web](https://tramflow.ru/) [anchor](#checks)')
        self.assertEqual(bundle_readme(text),
            '[status](tram-forecast/docs/submission-final/final-closure-status.md#checks) '
            '[model](tram-forecast/ml/README.md) [web](https://tramflow.ru/) [anchor](#checks)')

    def test_evidence_requires_exact_checksums_and_safe_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'input'
            root.mkdir()
            (root / 'log.txt').write_text('passed\n')
            digest = sha(root / 'log.txt')
            manifest = root / 'SHA256SUMS'
            manifest.write_text(f'{digest}  log.txt\n')
            self.assertEqual(additional_evidence(root, Path(tmp) / 'out'), {'log.txt': digest})
            with self.assertRaises(ValueError):
                additional_evidence(root, Path(tmp) / 'out')
            (root / 'unlisted.txt').write_text('unreviewed')
            with self.assertRaises(ValueError):
                additional_evidence(root, Path(tmp) / 'other')
            (root / 'unlisted.txt').unlink()
            for name in ('../input/log.txt', '/log.txt', 'log.txt\n' + digest + '  log.txt'):
                manifest.write_text(f'{digest}  {name}\n')
                with self.assertRaises(ValueError):
                    additional_evidence(root, Path(tmp) / 'other')
            manifest.write_text(f'{digest}  log.txt\n')
            (root / 'log.txt').write_text('changed')
            with self.assertRaises(ValueError):
                additional_evidence(root, Path(tmp) / 'other')

    def test_acceptance_rejects_changed_code_missing_checks_and_wrong_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'sources.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('tram-forecast/frontend/code.ts', 'original')
                z.writestr('tram-forecast/README.md', 'documentation')
            proof = {'status': 'passed', 'run_id': 'accepted-run', 'runtime_sha256': runtime_hashes(archive),
                     'checks': dict.fromkeys(['backend', 'integration', 'frontend_build', 'browser_chromium', 'browser_webkit', 'clean_launch', 'api_csv', 'restart'], 'passed')}
            accept_runtime(proof, archive, 'accepted-run')
            with self.assertRaises(ValueError):
                accept_runtime(proof, archive, 'other-run')
            changed = json.loads(json.dumps(proof))
            changed['checks'].pop('restart')
            with self.assertRaises(ValueError):
                accept_runtime(changed, archive, 'accepted-run')
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('tram-forecast/frontend/code.ts', 'changed')
            with self.assertRaises(ValueError):
                accept_runtime(proof, archive, 'accepted-run')


if __name__ == '__main__':
    unittest.main()
