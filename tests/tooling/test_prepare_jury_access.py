"""Credentials must never be generated in a public or versioned directory."""

from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_jury_access as generator


class PrivateDestinationTests(unittest.TestCase):
    def run_cli(self, *args):
        with patch("sys.argv", ["prepare_jury_access", *map(str, args)]):
            generator.main()

    def test_public_and_repository_paths_fail_before_hashing(self):
        repository = Path(generator.__file__).resolve().parents[1]
        for destination in (repository / "output/credentials", Path("/srv/tramflow"),
                            Path("/srv/tramflow/private/jury"),
                            Path("/srv/tramflow-before-20260925/jury"),
                            Path("/srv/tramflow-build.abc/jury"),
                            Path("/opt/tramflow-backups/release/jury")):
            with self.subTest(destination=destination), patch.object(generator.subprocess, "run") as caddy:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                    self.run_cli("--output-dir", destination)
                self.assertEqual(exc.exception.code, 2)
                caddy.assert_not_called()

    def test_custom_web_root_and_environment_are_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp) / "public"
            destination = web / "jury"
            for args, env in ((["--web-root", web], {}), ([], {"TRAMFLOW_ROOT": str(web)})):
                with self.subTest(args=args), patch.dict(os.environ, env), \
                        patch.object(generator.subprocess, "run") as caddy:
                    with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                        self.run_cli("--output-dir", destination, *args)
                    self.assertEqual(exc.exception.code, 2)
                    caddy.assert_not_called()
                    self.assertFalse(destination.exists())

    def test_symlink_into_site_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web = root / "public"
            web.mkdir()
            alias = root / "apparently-private"
            alias.symlink_to(web, target_is_directory=True)
            with self.assertRaises(ValueError):
                generator.private_destination(alias / "jury", web)

    def test_symlink_out_of_site_is_also_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web, private = root / "public", root / "private"
            web.mkdir()
            private.mkdir()
            (web / "alias").symlink_to(private, target_is_directory=True)
            with self.assertRaises(ValueError):
                generator.private_destination(web / "alias/jury", web)

    def test_sibling_of_custom_root_can_be_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "public-private/jury"
            self.assertEqual(generator.private_destination(destination, root / "public"),
                             destination.resolve())

    def test_private_output_permissions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "jury"
            # Valid hash shape is enough here; Caddy authentication is tested separately.
            result = subprocess.CompletedProcess([], 0, "$2a$14$" + "a" * 53, "")
            with patch.object(generator.subprocess, "run", return_value=result):
                self.run_cli("--output-dir", destination)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            original = {p.name: p.read_bytes() for p in destination.iterdir()}
            self.assertEqual(set(original), {"jury-access.txt", "jury.netrc", "tramflow-users.caddy"})
            for p in destination.iterdir():
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            with patch.object(generator.subprocess, "run") as caddy:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    self.run_cli("--output-dir", destination)
                caddy.assert_not_called()
            self.assertEqual(original, {p.name: p.read_bytes() for p in destination.iterdir()})


if __name__ == "__main__":
    unittest.main()
