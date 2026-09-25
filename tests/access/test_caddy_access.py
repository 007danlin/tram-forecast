"""Run explicitly with CADDY_BIN; missing Caddy is an error, not a passing skip."""

import base64
import json
import os
import shutil
import subprocess
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ml.forecast import predict_mock
from support import protected_stack


class CaddyAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caddy = os.environ.get("CADDY_BIN") or shutil.which("caddy")
        if not cls.caddy:
            raise RuntimeError("Set CADDY_BIN to Caddy >= 2.8 for access tests.")
        cls.manager = protected_stack(cls.caddy)
        cls.stack = cls.manager.__enter__()
        cls.addClassCleanup(cls.manager.__exit__, None, None, None)

    def request(self, path, password=None, method="GET"):
        headers = {}
        if password is not None:
            token = base64.b64encode(f"{self.stack.username}:{password}".encode()).decode()
            headers["Authorization"] = "Basic " + token
        req = Request(self.stack.base_url + path, headers=headers, method=method)
        try:
            response = urlopen(req, context=self.stack.context, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    def test_unauthenticated_ui_assets_api_and_fallback_are_closed(self):
        for path in ("/", "/map-local/network.json", "/api/v1/health",
                     "/api/v1/forecast", "/docs", "/openapi.json", "/not-found"):
            with self.subTest(path=path):
                status, headers, _ = self.request(path)
                self.assertEqual(status, 401)
                self.assertIn("Basic", headers["WWW-Authenticate"])
        self.assertEqual(self.request("/api/v1/forecast", method="HEAD")[0], 401)

    def test_wrong_password_is_rejected(self):
        for path in ("/", "/api/v1/forecast"):
            self.assertEqual(self.request(path, "wrong-password")[0], 401)

    def test_authorized_static_and_real_v1_are_unchanged(self):
        for path in ("/", "/map-local/network.json"):
            self.assertEqual(self.request(path, self.stack.password)[0], 200)
        status, _, body = self.request("/api/v1/health", self.stack.password)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})
        status, _, body = self.request("/api/v1/forecast", self.stack.password)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), predict_mock())

    def test_proxy_does_not_forward_password_to_backend(self):
        self.stack.seen_headers.clear()
        self.assertEqual(self.request("/api/v1/health", self.stack.password)[0], 200)
        self.assertTrue(self.stack.seen_headers)
        self.assertNotIn(b"authorization", self.stack.seen_headers[-1])

    def test_missing_private_file_fails_closed(self):
        env = self.stack.env | {"TRAMFLOW_AUTH_FILE": str(self.stack.temp / "missing.caddy")}
        result = subprocess.run(
            [self.caddy, "validate", "--config", str(self.stack.config), "--adapter", "caddyfile"],
            env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_curl_netrc_for_update_checks(self):
        netrc = self.stack.temp / "local.netrc"
        netrc.write_text(
            f"machine localhost\nlogin {self.stack.username}\npassword {self.stack.password}\n"
        )
        netrc.chmod(0o600)
        common = ["curl", "--noproxy", "*", "--fail", "--silent", "--show-error", "--max-time", "5",
                  "--cacert", str(self.stack.ca_file)]
        anonymous = subprocess.run(common + ["--write-out", "%{http_code}", "--output", os.devnull,
                                            self.stack.base_url + "/"], capture_output=True)
        self.assertNotEqual(anonymous.returncode, 0)
        self.assertEqual(anonymous.stdout, b"401")
        for path in ("/", "/map-local/network.json", "/api/v1/health"):
            result = subprocess.run(common + ["--netrc-file", str(netrc),
                                              self.stack.base_url + path], capture_output=True)
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
