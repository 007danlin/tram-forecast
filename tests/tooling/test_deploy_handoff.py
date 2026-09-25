"""Exercise deployment selection without Docker, root access or a live server."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).resolve().parents[2] / "deploy/handoff.sh"
SHELL = r'''
set -euo pipefail
docker() {
  if [[ "$1" == compose && " $* " == *" ps "* ]]; then
    if [[ "$CASE" != empty && ( "$CASE" != stopped || " $* " == *" --all "* ) ]]; then
      printf '%s\n' container-id
    fi
  elif [[ "$1" == inspect && "$3" == *'.Mounts'* ]]; then
    if [[ "$CASE" == running || "$CASE" == stopped ]]; then printf '%s\n' "$OLD_RELEASE"; fi
  elif [[ "$1" == inspect && "$3" == *'.Config.Env'* ]]; then
    if [[ "$CASE" == unmanaged ]]; then printf '%s\n' 'TRAMFLOW_HANDOFF_DIR=/custom/path'; fi
  elif [[ "$1" == compose && " $* " == *" config "* ]]; then
    printf '%s\n' "validated=$*"
  else
    echo "Unexpected Docker operation: $*" >&2
    return 99
  fi
}
source "$HELPER"
select_handoff
printf 'selected=%s\nprevious=%s\n' "${TRAMFLOW_HANDOFF_HOST_DIR:-}" "$previous_handoff"
'''


class HandoffDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="handoff selection ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old = self.root / "previous release"
        self.new = self.root / "new release"
        for path in (self.old, self.new):
            path.mkdir()
            (path / "receipt.json").write_text("{}")

    def run_selection(self, scenario, explicit=None):
        env = os.environ.copy()
        env.pop("TRAMFLOW_HANDOFF_HOST_DIR", None)
        env.update(HELPER=str(HELPER), CASE=scenario, OLD_RELEASE=str(self.old))
        if explicit is not None:
            env["TRAMFLOW_HANDOFF_HOST_DIR"] = str(explicit)
        return subprocess.run(["bash", "-c", SHELL], env=env, text=True, capture_output=True)

    def test_initial_setup_has_no_handoff(self):
        result = self.run_selection("empty")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("compose.handoff.yaml", result.stdout)

    def test_running_and_stopped_service_preserve_release_in_fresh_shell(self):
        for scenario in ("running", "stopped"):
            with self.subTest(scenario=scenario):
                result = self.run_selection(scenario)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("compose.handoff.yaml", result.stdout)
                self.assertIn(f"selected={self.old}", result.stdout)

    def test_explicit_new_release_wins_and_previous_is_retained_for_rollback(self):
        result = self.run_selection("running", self.new)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"selected={self.new}", result.stdout)
        self.assertIn(f"previous={self.old}", result.stdout)

    def test_missing_receipt_and_relative_paths_stop_before_compose_validation(self):
        (self.new / "receipt.json").unlink()
        for invalid in (self.new, "relative/path", self.root / "absent"):
            with self.subTest(path=invalid):
                result = self.run_selection("running", invalid)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("validated=", result.stdout)

    def test_unmanaged_mount_requires_explicit_release(self):
        result = self.run_selection("unmanaged")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("validated=", result.stdout)
        self.assertEqual(self.run_selection("unmanaged", self.new).returncode, 0)


if __name__ == "__main__":
    unittest.main()
