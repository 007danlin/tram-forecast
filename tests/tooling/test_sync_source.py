"""Server source migration tests against disposable local Git repositories."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "deploy/sync-source.sh"


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote"
        self.server = self.root / "server"
        self.git(self.root, "init", "-q", "-b", "main", str(self.remote))
        self.commit("old", "initial")
        self.git(self.root, "clone", "-q", str(self.remote), str(self.server))
        self.before = self.git(self.server, "rev-parse", "HEAD")

    def git(self, root, *args):
        return subprocess.check_output([
            "git", "-C", str(root), "-c", "user.name=Delivery Test",
            "-c", "user.email=delivery@example.test", *args,
        ], text=True, stderr=subprocess.PIPE).strip()

    def commit(self, content, message):
        (self.remote / "app.txt").write_text(content)
        self.git(self.remote, "add", "app.txt")
        self.git(self.remote, "commit", "-q", "-m", message)

    def sync(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=self.server,
                              env=os.environ.copy(), text=True, capture_output=True)

    def test_check_does_not_update_then_fast_forward_preserves_backup(self):
        self.commit("new", "update")
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.server, "rev-parse", "HEAD"), self.before)
        result = self.sync("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.server / "app.txt").read_text(), "new")
        refs = self.git(self.server, "for-each-ref", "--format=%(objectname)", "refs/tramflow-backups")
        self.assertEqual(refs, self.before)

    def test_rewritten_history_with_identical_old_tree_can_migrate(self):
        self.git(self.remote, "commit", "--amend", "-q", "-m", "rewritten metadata")
        self.commit("new", "subsequent update")
        result = self.sync("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rewritten-history", result.stdout)
        self.assertEqual(self.git(self.server, "rev-parse", "HEAD"), self.git(self.remote, "rev-parse", "HEAD"))
        self.assertEqual(self.git(self.server, "for-each-ref", "--format=%(objectname)", "refs/tramflow-backups"), self.before)

    def test_real_divergence_is_refused(self):
        self.git(self.remote, "checkout", "--orphan", "replacement")
        self.commit("unrelated", "unrelated root")
        self.git(self.remote, "branch", "-f", "main", "HEAD")
        result = self.sync("--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.server, "rev-parse", "HEAD"), self.before)
        self.assertEqual((self.server / "app.txt").read_text(), "old")

    def test_dirty_and_untracked_files_are_preserved(self):
        self.commit("new", "update")
        for name in ("app.txt", "untracked.txt"):
            with self.subTest(name=name):
                path = self.server / name
                path.write_text("local work")
                result = self.sync("--apply")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text(), "local work")
                self.assertEqual(self.git(self.server, "rev-parse", "HEAD"), self.before)
                if name == "app.txt":
                    path.write_text("old")
                else:
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
