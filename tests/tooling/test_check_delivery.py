"""Check omissions that a successful build in a dirty checkout would conceal."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.check_delivery import REQUIRED, check


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        for name in REQUIRED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")
        self.git("add", ".")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def test_complete_source_and_ignored_local_artifact(self):
        (self.root / ".gitignore").write_text("artifacts/\n")
        (self.root / "artifacts").mkdir()
        (self.root / "artifacts/model.joblib").write_bytes(b"synthetic")
        self.assertEqual(check(self.root), [])

    def test_untracked_required_file_is_not_a_delivery(self):
        self.git("rm", "--cached", "deploy/handoff.sh")
        errors = check(self.root)
        self.assertTrue(any("Not included in Git: deploy/handoff.sh" in e for e in errors))
        self.assertTrue(any("Required delivery file" in e and "deploy/handoff.sh" in e for e in errors))

    def test_deleted_tracked_map_is_reported(self):
        (self.root / "frontend/public/map-local/network.json").unlink()
        self.assertTrue(any("missing from disk" in e for e in check(self.root)))

    def test_link_to_local_only_document_fails(self):
        (self.root / "README.md").write_text("[instructions](docs/unpublished.md)\n")
        (self.root / "docs").mkdir()
        (self.root / "docs/unpublished.md").write_text("not sent\n")
        self.assertTrue(any("Documentation target not in Git" in e for e in check(self.root)))

    def test_forced_local_files_are_rejected(self):
        for name in (".env.production", "frontend/model.joblib", "real-forecast.csv", "data/train.csv",
                     "output/md/tramflow-team-specs.md", "output/pdf/tramflow-team-specs.pdf"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic fixture")
            self.git("add", "-f", name)
        errors = check(self.root)
        self.assertEqual(sum("must not be in source delivery" in e for e in errors), 6)


if __name__ == "__main__":
    unittest.main()
