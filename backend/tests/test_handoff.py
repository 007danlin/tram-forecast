"""Synthetic release and real HTTP tests; supplied data is never committed."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

import uvicorn

from backend.handoff.api import HandoffError, Query, calculate
from backend.handoff.install import install, MEMBERS
from backend.handoff.store import COLUMNS, SCHEMA, digest, load_snapshot
from backend.main import app, lifespan


def make_archive(root, *, missing=False, defect=None):
    metadata = {
        "schema_version": SCHEMA,
        "unit": "successful_boardings",
        "grain": ["route", "date", "hour"],
        "product_timezone_contract": "Europe/Moscow",
        "supported_routes": [1],
        "cold_start_routes": [5],
        "limitations": ["Synthetic fixture"],
        "interval": {"method": "synthetic interval"},
    }
    if defect == "version":
        metadata["schema_version"] = "unsupported"
    if defect == "interval_null":
        metadata["interval"] = None
    if defect == "interval_missing":
        metadata.pop("interval")
    if defect == "method_missing":
        metadata["interval"] = {}
    for label, value in (
        ("method_null", None),
        ("method_number", 12),
        ("method_list", []),
        ("method_blank", "  "),
        ("method_empty", ""),
    ):
        if defect == label:
            metadata["interval"]["method"] = value
    files = {
        "model.joblib": b"Not a pickle: must never be deserialized",
        "metadata.json": json.dumps(metadata).encode(),
        "feature-schema.json": json.dumps(
            {
                "schema_version": SCHEMA,
                "keys": {"route": "int", "date": "YYYY-MM-DD", "hour": "int[0,23]"},
            }
        ).encode(),
    }
    files["manifest.json"] = json.dumps(
        {
            "schema_version": SCHEMA,
            "files": {k: digest(v) for k, v in files.items()},
            "source_checksums": {"train.csv": "synthetic"},
        }
    ).encode()
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(COLUMNS)
    for route in (1, 5):
        for hour in range(24):
            if missing and route == 1 and hour == 12:
                continue
            value = 1.4 if route == 1 else 0.0
            row = [
                route,
                "2025-11-01",
                hour,
                value,
                1.0,
                0.0,
                2.0,
                0.0,
                "ok" if route == 1 else "cold_start_zero_baseline",
            ]
            if route == 1 and hour == 0:
                if defect == "nan":
                    row[3] = "nan"
                if defect == "negative":
                    row[3] = -1
                if defect == "bounds":
                    row[6] = 0.1
                if defect == "status":
                    row[8] = "cold_start_zero_baseline"
                if defect == "unknown":
                    row[0] = 999
                if defect == "duplicate":
                    writer.writerow(row)
            writer.writerow(row)
    files["forecast.csv"] = stream.getvalue().encode()
    archive = root / "handoff.zip"
    with ZipFile(archive, "w") as z:
        for name, data in files.items():
            z.writestr(MEMBERS[name], data)
        z.writestr("../../must-not-extract.txt", "ignored")
    return archive


def day_query(**changes):
    return Query.model_validate(
        {
            "route_ids": ["1"],
            "start": "2025-11-01T00:00:00+03:00",
            "end": "2025-11-02T00:00:00+03:00",
            **changes,
        }
    )


class HandoffTests(unittest.TestCase):
    def test_failed_startup_does_not_expose_a_previous_snapshot(self):
        async def verify():
            app.state.handoff_snapshot = object()
            with tempfile.TemporaryDirectory() as tmp:
                with patch.dict(os.environ, {"TRAMFLOW_HANDOFF_DIR": tmp}):
                    with self.assertLogs("backend.main", level="ERROR"):
                        async with lifespan(app):
                            self.assertIsNone(app.state.handoff_snapshot)

        asyncio.run(verify())

    def test_import_query_precision_daily_and_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = install(make_archive(root), root / "release")
            snapshot = load_snapshot(root / "release")
            hourly = calculate(snapshot, day_query(), "one")
            daily = calculate(snapshot, day_query(resolution="day"), "two")
            self.assertEqual(len(hourly.rows), 24)
            self.assertAlmostEqual(daily.rows[0].value, 33.6)
            self.assertEqual(hourly.total, daily.total)
            self.assertIsNone(daily.rows[0].upper_90)
            baseline = calculate(snapshot, day_query(route_ids=["5"]), "three")
            self.assertEqual(baseline.total, 0)
            self.assertTrue(
                all(r.status == "cold_start_zero_baseline" for r in baseline.rows)
            )
            self.assertEqual(snapshot.run_id, run)
            self.assertFalse((root / "must-not-extract.txt").exists())
            with self.assertRaises(ValueError):
                install(root / "handoff.zip", root / "release")

    def test_partial_day_and_missing_day_are_not_full_or_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install(make_archive(root, missing=True), root / "release")
            snapshot = load_snapshot(root / "release")
            result = calculate(snapshot, day_query(resolution="day"), "one")
            self.assertEqual(result.total_scope, "available_only")
            self.assertEqual(result.rows[0].status, "partial")
            self.assertEqual(result.coverage, 23 / 24)
            self.assertAlmostEqual(result.total, 32.2)
            result = calculate(
                snapshot,
                day_query(
                    start="2025-11-02T00:00:00+03:00", end="2025-11-03T00:00:00+03:00"
                ),
                "two",
            )
            self.assertIsNone(result.total)
            self.assertTrue(all(r.value is None for r in result.rows))

    def test_corrupt_and_incompatible_candidates_never_publish(self):
        for defect in (
            "version",
            "nan",
            "negative",
            "bounds",
            "status",
            "unknown",
            "duplicate",
            "interval_null",
            "interval_missing",
            "method_missing",
            "method_null",
            "method_number",
            "method_list",
            "method_blank",
            "method_empty",
        ):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaises(ValueError):
                    install(make_archive(root, defect=defect), root / "release")
                self.assertFalse((root / "release").exists())

    def test_modified_csv_is_rejected_after_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install(make_archive(root), root / "release")
            with (root / "release" / "forecast.csv").open("ab") as file:
                file.write(b"\n")
            with self.assertRaises(ValueError):
                load_snapshot(root / "release")

    def test_canonical_query_identity_and_run_pinning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install(make_archive(root), root / "release")
            snapshot = load_snapshot(root / "release")
            a = calculate(snapshot, day_query(route_ids=["5", "1", "1"]), "a")
            b = calculate(
                snapshot,
                day_query(
                    route_ids=["1", "5"],
                    start="2025-10-31T21:00:00Z",
                    end="2025-11-01T21:00:00Z",
                ),
                "b",
            )
            self.assertEqual(a.result_id, b.result_id)
            with self.assertRaises(HandoffError) as exc:
                calculate(snapshot, day_query(forecast_run_id="old"), "c")
            self.assertEqual(exc.exception.status, 410)


class HandoffHttpTests(unittest.TestCase):
    def test_live_responses_match_documented_models(self):
        from backend.handoff.api import (
            HandoffReady,
            HandoffCapabilities,
            HandoffErrorResponse,
            HandoffValidationResponse,
        )

        schema = app.openapi()
        prefix = "/api/v2/handoff"
        cases = [
            ("/ready", None, 200, HandoffReady),
            ("/capabilities", None, 200, HandoffCapabilities),
            ("/query", {}, 422, HandoffValidationResponse),
            (
                "/query",
                day_query(route_ids=["999"]).model_dump(mode="json"),
                404,
                HandoffErrorResponse,
            ),
            (
                "/query",
                day_query(forecast_run_id="old").model_dump(mode="json"),
                410,
                HandoffErrorResponse,
            ),
        ]
        for path, body, expected, model in cases:
            with self.subTest(path=path, status=expected):
                status, headers, raw = self.call(prefix + path, body)
                self.assertEqual(status, expected)
                payload = json.loads(raw)
                model.model_validate(payload)
                operation = schema["paths"][prefix + path][
                    "get" if body is None else "post"
                ]
                ref = operation["responses"][str(status)]["content"][
                    "application/json"
                ]["schema"]["$ref"]
                self.assertEqual(ref, "#/components/schemas/" + model.__name__)
                if status != 200:
                    self.assertEqual(
                        payload["error"]["request_id"], headers["X-Request-Id"]
                    )
        for path in ("/query", "/export"):
            responses = schema["paths"][prefix + path]["post"]["responses"]
            self.assertTrue({"404", "410", "413", "422", "503"}.issubset(responses))
        self.assertIn("409", schema["paths"][prefix + "/export"]["post"]["responses"])
        with patch.object(app.state, "handoff_snapshot", None):
            for path in ("/ready", "/capabilities"):
                status, _, raw = self.call(prefix + path)
                self.assertEqual(status, 503)
                HandoffErrorResponse.model_validate_json(raw)

    def test_capabilities_preserve_scenario_and_qualitative_year(self):
        from backend.handoff.features import SCENARIO, YEAR

        status, _, raw = self.call("/api/v2/handoff/capabilities")
        self.assertEqual(status, 200)
        payload = json.loads(raw)
        self.assertTrue(payload["scenario_supported"])
        self.assertEqual(payload["scenario"], SCENARIO)
        self.assertEqual(payload["year"], YEAR)
        schema = app.openapi()["components"]["schemas"]
        required = schema["HandoffCapabilities"]["required"]
        self.assertTrue({"scenario_supported", "scenario", "year"}.issubset(required))
        self.assertEqual(
            schema["HandoffYearCapabilities"]["properties"]["numeric_supported"]["const"],
            False,
        )

    def test_parallel_clients_do_not_share_filters(self):
        def fetch(route):
            status, _, raw = self.call(
                "/api/v2/handoff/query",
                day_query(route_ids=[route]).model_dump(mode="json"),
            )
            self.assertEqual(status, 200)
            return json.loads(raw)

        routes = ["1", "5"] * 5
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(fetch, routes))
        for route, result in zip(routes, results):
            self.assertEqual({row["route_id"] for row in result["rows"]}, {route})
            self.assertAlmostEqual(result["total"], 33.6 if route == "1" else 0)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        install(make_archive(root), root / "release")
        cls.env = patch.dict(
            os.environ, {"TRAMFLOW_HANDOFF_DIR": str(root / "release")}
        )
        cls.env.start()
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.sock.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        cls.thread = threading.Thread(
            target=cls.server.run, kwargs={"sockets": [cls.sock]}, daemon=True
        )
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                return
            time.sleep(0.05)
        cls.tearDownClass()
        raise RuntimeError("Server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.sock.close()
        cls.env.stop()
        cls.tmp.cleanup()

    def call(self, path, body=None):
        request = Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_http_query_export_and_errors(self):
        prefix = "/api/v2/handoff"
        self.assertEqual(self.call(prefix + "/ready")[0], 200)
        self.assertEqual(self.call("/api/v1/health")[0], 200)
        self.assertEqual(self.call(prefix + "/capabilities")[0], 200)
        payload = day_query().model_dump(mode="json")
        status, _, raw = self.call(prefix + "/query", payload)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        body = {**result["filters"], "expected_result_id": result["result_id"]}
        status, headers, raw = self.call(prefix + "/export", body)
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Result-Id"], result["result_id"])
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual(
            [float(r["value"]) for r in rows], [r["value"] for r in result["rows"]]
        )
        for changes, expected in (
            ({"expected_result_id": "wrong"}, 409),
            ({"forecast_run_id": "old"}, 410),
        ):
            self.assertEqual(
                self.call(prefix + "/export", {**body, **changes})[0], expected
            )
        for changes, expected in (
            ({"route_ids": ["999"]}, 404),
            ({"resolution": "month"}, 422),
            ({"direction_id": "0"}, 422),
        ):
            status, _, raw = self.call(prefix + "/query", {**payload, **changes})
            self.assertEqual(status, expected)
            self.assertIn("request_id", json.loads(raw)["error"])
        with patch.object(app.state, "handoff_snapshot", None):
            self.assertEqual(self.call(prefix + "/ready")[0], 503)
            self.assertEqual(self.call("/api/v1/health")[0], 200)


if __name__ == "__main__":
    unittest.main()
