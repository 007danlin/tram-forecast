"""Real HTTP checks using unittest + the application's existing dependencies."""
import json
from datetime import datetime, timedelta
from pathlib import Path
import re
import socket
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

import uvicorn
from backend.main import app
from ml import forecast


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.sock.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.sock]}, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                return
            time.sleep(0.05)
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.sock.close()
        raise RuntimeError("Test HTTP server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.sock.close()

    def get(self, path):
        with urlopen(self.base + path, timeout=3) as response:
            return json.load(response)

    def test_health(self):
        self.assertEqual(self.get("/api/v1/health"), {"status": "ok"})

    def test_backend_calls_ml_and_returns_its_values(self):
        example = forecast.predict_mock()
        example["points"][0]["value"] = 73
        with patch("ml.forecast.predict_mock", return_value=example) as mock:
            self.assertEqual(self.get("/api/v1/forecast"), example)
            mock.assert_called_once_with()

    def test_contract_matches_documentation(self):
        text = Path("INTEGRATION.md").read_text()
        examples = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
        data = self.get("/api/v1/forecast")
        self.assertEqual(data, next(e for e in examples if "points" in e))
        self.assertIs(data["is_mock"], True)
        self.assertEqual(data["unit"], "passengers")
        dates = [datetime.fromisoformat(p["timestamp"]) for p in data["points"]]
        self.assertTrue(all(d.utcoffset() == timedelta(hours=3) for d in dates))
        self.assertTrue(all(a < b for a, b in zip(dates, dates[1:])))
        self.assertTrue(all(type(p["value"]) is int and p["value"] >= 0 for p in data["points"]))

    def test_mock_is_deterministic_and_returns_fresh_data(self):
        first = forecast.predict_mock()
        second = forecast.predict_mock()
        self.assertEqual(first, second)
        first["points"][0]["value"] = -1
        self.assertEqual(forecast.predict_mock(), second)

    def assert_unavailable(self):
        with self.assertRaises(HTTPError) as raised:
            self.get("/api/v1/forecast")
        self.assertEqual(raised.exception.code, 503)
        with raised.exception as response:
            self.assertEqual(json.load(response), {"detail": "Forecast temporarily unavailable"})

    def test_ml_exception_is_reported_as_503(self):
        with patch("ml.forecast.predict_mock", side_effect=RuntimeError("test failure")):
            with self.assertLogs("backend.main", level="ERROR"):
                self.assert_unavailable()

    def test_invalid_ml_response_is_reported_as_503(self):
        invalid = forecast.predict_mock()
        invalid["points"][0]["timestamp"] = "2026-01-01T09:00:00"
        with patch("ml.forecast.predict_mock", return_value=invalid):
            with self.assertLogs("backend.main", level="ERROR"):
                self.assert_unavailable()

    def test_incompatible_ml_contract_is_rejected_before_inference(self):
        for version in ("synthetic-v2", "", None):
            with self.subTest(version=version):
                with patch.object(forecast, "CONTRACT_VERSION", version):
                    with patch("ml.forecast.predict_mock") as mock:
                        with self.assertLogs("backend.main", level="ERROR"):
                            self.assert_unavailable()
                        mock.assert_not_called()
        self.assertEqual(self.get("/api/v1/forecast"), forecast.predict_mock())

    def test_missing_ml_contract_is_rejected_before_inference(self):
        with patch.object(forecast, "CONTRACT_VERSION"):
            del forecast.CONTRACT_VERSION
            with patch("ml.forecast.predict_mock") as mock:
                with self.assertLogs("backend.main", level="ERROR"):
                    self.assert_unavailable()
                mock.assert_not_called()

    def test_openapi_available(self):
        schema = self.get("/openapi.json")
        self.assertIn("/api/v1/forecast", schema["paths"])


if __name__ == "__main__":
    unittest.main()
