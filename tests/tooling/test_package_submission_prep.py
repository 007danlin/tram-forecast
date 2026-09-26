"""A rebuilt handoff must contain current source bytes and exclude local artifacts."""

from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from scripts import package_submission_prep as packager
from scripts.check_delivery import REQUIRED


class PackageTests(unittest.TestCase):
    def test_rebuild_uses_current_sources_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "repository"
            sources = {"INTEGRATION.md": b"current contract\n",
                       "ml/reports/experiment-log.csv": b"experiment,score\nexample,0.5\n",
                       "scripts/example.py": b"print('current source')\n"}
            excluded = {"output/release/old.md": b"superseded instruction",
                        "data/private.csv": b"local data",
                        "scripts/local-review.json": b'{"private": "untracked note"}',
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
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "frontend").mkdir()
            (root / "frontend/Dockerfile").write_text("FROM scratch\n")
            subprocess.run(["git", "-C", str(root), "add", "--", *sources, "frontend/Dockerfile"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c",
                            "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
            # Tracked working bytes, not stale index bytes, belong to the snapshot.
            sources["scripts/example.py"] = b"print('reviewed working change')\n"
            (root / "scripts/example.py").write_bytes(sources["scripts/example.py"])
            with patch.object(packager, "ROOT", root), \
                    patch.object(packager, "ROOT_FILES", ("INTEGRATION.md", "ml/reports/experiment-log.csv")), \
                    patch.object(packager, "SOURCE_DIRS", ("scripts", "ml")), \
                    patch("sys.argv", args):
                packager.main()
                second = Path(tmp) / "repeat"
                with patch("sys.argv", ["package_submission_prep", "--output-dir", str(second)]):
                    packager.main()
            archive = destination / "web-handoff-preparation.zip"
            self.assertEqual(archive.read_bytes(), (second / archive.name).read_bytes())
            with ZipFile(archive) as z:
                for name, content in sources.items():
                    self.assertEqual(z.read("tram-forecast/" + name), content)
                for name in excluded:
                    self.assertNotIn("tram-forecast/" + name, z.namelist())
            for line in (destination / "SHA256SUMS").read_text().splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((destination / name).read_bytes()).hexdigest(), digest)
            report = json.loads((destination / "verification.json").read_text())
            self.assertEqual(report["source_commit"], subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip())
            self.assertTrue(report["source_dirty"])
            self.assertEqual(report["scope"], "archive_integrity_only")
            self.assertEqual(report["archives"][archive.name]["sha256"],
                             hashlib.sha256(archive.read_bytes()).hexdigest())
            before = archive.read_bytes()
            with patch("sys.argv", args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                packager.main()
            self.assertEqual(archive.read_bytes(), before)

    def test_real_source_archive_contains_handoff_launch_and_no_local_artifacts(self):
        """Exercise actual delivery selection, so omitted root overlays cannot hide in mocks."""
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "release"
            with patch("sys.argv", ["package_submission_prep", "--output-dir", str(destination),
                     "--include-list", str(packager.ROOT / "docs/submission-final/source-allowlist.json")]):
                packager.main()
            with ZipFile(destination / "web-handoff-preparation.zip") as z:
                names = {n.removeprefix("tram-forecast/") for n in z.namelist()}
                self.assertTrue(set(REQUIRED).issubset(names), sorted(set(REQUIRED) - names))
                for name in ("compose.yaml", "compose.handoff.yaml", "compose.load.yaml", "compose.monitoring.yaml",
                             "backend/handoff/install.py", "backend/requirements.txt",
                             "frontend/public/map-local/network.json", "frontend/public/tram-icon.png", "frontend/public/favicon.svg", "tests/load/handoff.js",
                             "frontend/public/map-local/schematic.svg", "frontend/public/map-local/schematic.meta.json",
                             "frontend/public/fonts/Manrope.woff2", "frontend/public/fonts/OFL-Manrope.txt",
                             "frontend/public/theme-init.js", "frontend/public/theme-base.css"):
                    self.assertIn(name, names)
                self.assertFalse(any(packager.local_only(name) for name in names))
                note = z.read("tram-forecast/PREPARATION-README.md").decode()
                self.assertIn("compose.handoff.yaml", note)
                self.assertNotIn("Режим web: synthetic v1", note)

    def test_explicit_new_sources_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "repo"
            (root / "frontend").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "frontend/Dockerfile").write_text("FROM scratch")
            (root / "scripts/new.py").write_text("# reviewed new source\n")
            include = Path(tmp) / "include.json"
            include.write_text(json.dumps(["scripts/new.py"]))
            def git_output(command, **kwargs):
                if "rev-parse" in command:
                    return "a" * 40
                if "--others" in command:
                    return b"scripts/new.py\0"
                if "ls-files" in command:
                    return b"frontend/Dockerfile\0"
                return b""
            with patch.object(packager, "ROOT", root), patch.object(packager, "ROOT_FILES", ()), \
                    patch.object(packager.subprocess, "check_output", side_effect=git_output):
                with patch("sys.argv", ["pack", "--output-dir", str(Path(tmp)/"missing")]), \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    packager.main()
                with patch("sys.argv", ["pack", "--output-dir", str(Path(tmp)/"ok"), "--include-list", str(include)]):
                    packager.main()
                with ZipFile(Path(tmp)/"ok/web-handoff-preparation.zip") as z:
                    self.assertEqual(z.read("tram-forecast/scripts/new.py"), b"# reviewed new source\n")
                for unsafe in ["../private.py", "/tmp/private.py", "scripts/.env", "artifacts/private.json", "scripts/model.joblib"]:
                    include.write_text(json.dumps([unsafe]))
                    with patch("sys.argv", ["pack", "--output-dir", str(Path(tmp)/"bad"), "--include-list", str(include)]), \
                            redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        packager.main()

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
