"""A rebuilt handoff must contain current source bytes and exclude local artifacts."""

from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from scripts import package_submission_prep as packager


class PackageTests(unittest.TestCase):
    def test_rebuild_uses_current_sources_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "repository"
            sources = {"INTEGRATION.md": b"current contract\n",
                       "ml/reports/experiment-log.csv": b"experiment,score\nexample,0.5\n",
                       "scripts/example.py": b"print('current source')\n"}
            excluded = {"output/release/old.md": b"superseded instruction",
                        "data/private.csv": b"local data",
                        "ml/model.joblib": b"model",
                        "scripts/.env": b"not-for-package",
                        "scripts/jury-access.txt": b"not-for-package",
                        "scripts/jury.netrc": b"not-for-package"}
            for name, content in (sources | excluded).items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
            destination = Path(tmp) / "release"
            args = ["package_submission_prep", "--output-dir", str(destination)]
            with patch.object(packager, "ROOT", root), \
                    patch.object(packager, "ROOT_FILES", ("INTEGRATION.md", "ml/reports/experiment-log.csv")), \
                    patch.object(packager, "SOURCE_DIRS", ("scripts", "ml")), \
                    patch("sys.argv", args):
                (root / "frontend").mkdir()
                (root / "frontend/Dockerfile").write_text("FROM scratch\n")
                packager.main()
            archive = destination / "web-synthetic-preparation.zip"
            with ZipFile(archive) as z:
                for name, content in sources.items():
                    self.assertEqual(z.read("tram-forecast/" + name), content)
                for name in excluded:
                    self.assertNotIn("tram-forecast/" + name, z.namelist())
            for line in (destination / "SHA256SUMS").read_text().splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((destination / name).read_bytes()).hexdigest(), digest)
            report = json.loads((destination / "verification.json").read_text())
            self.assertEqual(report["scope"], "archive_integrity_only")
            self.assertEqual(report["archives"][archive.name]["sha256"],
                             hashlib.sha256(archive.read_bytes()).hexdigest())
            before = archive.read_bytes()
            with patch("sys.argv", args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                packager.main()
            self.assertEqual(archive.read_bytes(), before)

    def test_integrity_check_rejects_stale_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "stale.zip"
            stale = b"old instructions"
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as z:
                z.writestr("project/guide.md", stale)
                z.writestr("project/MANIFEST.sha256", hashlib.sha256(stale).hexdigest() + "  guide.md\n")
            with self.assertRaises(RuntimeError):
                packager.verify_archive(archive, "project/", {"guide.md": b"corrected instructions"})


if __name__ == "__main__":
    unittest.main()
