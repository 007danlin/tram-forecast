"""Synthetic full-period fixtures; no model execution or real data."""
import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from backend.handoff.install import install, MEMBERS
from backend.handoff.store import COLUMNS, SCHEMA, digest, load_snapshot
from scripts.package_ml_handoff import package, ROUTES


def make_package_inputs(root):
    model = root / 'model'
    model.mkdir()
    metadata = {
        'schema_version': SCHEMA, 'model_name': 'synthetic-test-model',
        'unit': 'successful_boardings', 'grain': ['route', 'date', 'hour'],
        'product_timezone_contract': 'Europe/Moscow',
        'supported_routes': sorted(int(r) for r in ROUTES - {'5'}),
        'cold_start_routes': [5], 'limitations': ['SYNTHETIC TEST FIXTURE'],
        'interval': {'method': 'synthetic'},
    }
    files = {
        'model.joblib': b'not executable: synthetic fixture',
        'metadata.json': json.dumps(metadata).encode(),
        'feature-schema.json': json.dumps({'schema_version': SCHEMA, 'keys': {'route': 'int', 'date': 'YYYY-MM-DD', 'hour': 'int[0,23]'}}).encode(),
    }
    files['manifest.json'] = json.dumps({'schema_version': SCHEMA, 'files': {k: digest(v) for k, v in files.items()}, 'source_checksums': {'synthetic': 'fixture'}}).encode()
    for name, value in files.items():
        (model / name).write_bytes(value)
    forecast = root / 'forecast.csv'
    with forecast.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(COLUMNS)
        for route in sorted(ROUTES, key=int):
            for d in range(61):
                for hour in range(24):
                    value = 0.0 if route == '5' else float(route) + hour / 7 + d / 13
                    writer.writerow([route, date(2025, 11, 1) + timedelta(days=d), hour, value, value, 0, value + 1, 0, 'cold_start_zero_baseline' if route == '5' else 'ok'])
    return model, forecast


class PackageTests(unittest.TestCase):
    def test_roundtrip_preserves_every_byte_and_deterministic_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, forecast = make_package_inputs(root)
            output = root / 'release.zip'
            checksum = package(model, forecast, output)
            self.assertEqual(checksum, digest(output.read_bytes()))
            self.assertEqual(checksum, package(model, forecast, root / 'second.zip'))
            self.assertTrue(output.with_suffix('.zip.sha256').read_text().startswith(checksum))
            with ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(MEMBERS.values()))
                for name, member in MEMBERS.items():
                    self.assertEqual(archive.read(member), (forecast if name == 'forecast.csv' else model / name).read_bytes())
            run = install(output, root / 'installed')
            self.assertEqual(run, load_snapshot(root / 'installed').run_id)
            with self.assertRaises(ValueError):
                package(model, forecast, output)

    def test_defects_never_publish(self):
        for defect in ('checksum', 'missing_hour', 'symlink', 'extra_factor', 'extra_manifest'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                model, forecast = make_package_inputs(root)
                if defect == 'checksum':
                    (model / 'model.joblib').write_bytes(b'changed')
                elif defect == 'missing_hour':
                    forecast.write_text('\n'.join(forecast.read_text().splitlines()[:-1]) + '\n')
                elif defect == 'symlink':
                    (root / 'source.bin').write_bytes((model / 'model.joblib').read_bytes())
                    (model / 'model.joblib').unlink()
                    (model / 'model.joblib').symlink_to(root / 'source.bin')
                elif defect == 'extra_factor':
                    (model / 'weather.csv').write_text('unsupported')
                else:
                    manifest = json.loads((model / 'manifest.json').read_text())
                    manifest['files']['weather.csv'] = 'unsupported'
                    (model / 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    package(model, forecast, root / 'bad.zip')
                self.assertFalse((root / 'bad.zip').exists())
                self.assertFalse((root / 'bad.zip.sha256').exists())


if __name__ == '__main__':
    unittest.main()
