"""Validate a complete release before exposing its immutable in-memory snapshot."""

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from backend.contracts.v2 import MOSCOW
from backend.contracts.v2 import parse_iso_datetime

SCHEMA = "tramflow-hourly-v1"
FILES = (
    "manifest.json",
    "metadata.json",
    "feature-schema.json",
    "model.joblib",
    "forecast.csv",
)
MAX_FILE_BYTES = 32 * 1024 * 1024
COLUMNS = [
    "route",
    "date",
    "hour",
    "prediction",
    "reference_value",
    "lower_90",
    "upper_90",
    "priority_score",
    "status",
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def release_id(hashes: dict) -> str:
    return "handoff-" + digest(json.dumps(hashes, sort_keys=True).encode())


@dataclass(frozen=True)
class Cell:
    prediction: float
    reference: float | None
    lower: float | None
    upper: float | None
    priority_score: float | None
    status: str


@dataclass(frozen=True)
class Snapshot:
    run_id: str
    model_version: str
    dataset_version: str
    csv_sha256: str
    imported_at: str
    routes: tuple[str, ...]
    cold_routes: tuple[str, ...]
    start: datetime
    end: datetime
    interval_method: str
    cells: Mapping[tuple[str, datetime], Cell]
    limitations: tuple[str, ...]


def read_limited(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Artifact exceeds size limit")
    return data


def load_snapshot(root: Path) -> Snapshot:
    receipt = json.loads(read_limited(root / "receipt.json"))
    imported_at = parse_iso_datetime(receipt["imported_at"])
    if imported_at.utcoffset() is None:
        raise ValueError("Receipt import timestamp must have a timezone")
    blobs = {name: read_limited(root / name) for name in FILES}
    hashes = {name: digest(data) for name, data in blobs.items()}
    if receipt.get("files") != hashes or receipt.get("forecast_run_id") != release_id(
        hashes
    ):
        raise ValueError("Release receipt checksum mismatch")
    manifest = json.loads(blobs["manifest.json"])
    metadata = json.loads(blobs["metadata.json"])
    features = json.loads(blobs["feature-schema.json"])
    for document in (manifest, metadata, features):
        if document.get("schema_version") != SCHEMA:
            raise ValueError("Unsupported ML schema version")
    expected_model_files = {
        name: hashes[name]
        for name in ("metadata.json", "feature-schema.json", "model.joblib")
    }
    if manifest.get("files") != expected_model_files:
        raise ValueError("Model manifest checksum mismatch")
    if metadata.get("unit") != "successful_boardings" or metadata.get("grain") != [
        "route",
        "date",
        "hour",
    ]:
        raise ValueError("Unsupported metric or grain")
    if metadata.get("product_timezone_contract") != "Europe/Moscow":
        raise ValueError("Unsupported product timezone")
    if features.get("keys") != {
        "route": "int",
        "date": "YYYY-MM-DD",
        "hour": "int[0,23]",
    }:
        raise ValueError("Unsupported feature keys")
    supported, cold = metadata["supported_routes"], metadata["cold_start_routes"]
    route_numbers = supported + cold
    if (
        not route_numbers
        or any(type(r) is not int or r <= 0 for r in route_numbers)
        or len(set(route_numbers)) != len(route_numbers)
    ):
        raise ValueError("Invalid route catalogue")
    routes = tuple(str(r) for r in sorted(route_numbers))
    cold_routes = tuple(str(r) for r in cold)
    interval = metadata.get("interval")
    if not isinstance(interval, dict):
        raise ValueError("Invalid interval metadata")
    interval_method = interval.get("method")
    if not isinstance(interval_method, str) or not interval_method.strip():
        raise ValueError("Interval method must be a non-empty string")
    forecast_kind = metadata.get("forecast_kind", "with-diagnostics-v1")
    if forecast_kind not in ("with-diagnostics-v1", "point-only-v1"):
        raise ValueError("Unsupported forecast kind")
    point_only = forecast_kind == "point-only-v1"
    if point_only and interval_method != "not_estimated":
        raise ValueError("Point-only forecasts must declare unestimated intervals")
    reader = csv.DictReader(
        io.StringIO(blobs["forecast.csv"].decode("utf-8-sig")), delimiter=";"
    )
    if reader.fieldnames != COLUMNS:
        raise ValueError("Unexpected forecast CSV columns")
    cells = {}
    for row in reader:
        if len(cells) >= 500000 or None in row or any(v is None for v in row.values()):
            raise ValueError("Invalid or oversized CSV")
        route = row["route"]
        if route not in routes:
            raise ValueError("Unknown route in CSV")
        day, hour = date.fromisoformat(row["date"]), int(row["hour"])
        if row["date"] != day.isoformat() or not 0 <= hour <= 23:
            raise ValueError("Invalid calendar cell")
        start = datetime(day.year, day.month, day.day, hour, tzinfo=MOSCOW)
        key = (route, start)
        if key in cells:
            raise ValueError("Duplicate forecast cell")
        if point_only:
            if any(row[k] != "" for k in COLUMNS[4:8]):
                raise ValueError("Point-only forecasts cannot claim diagnostic values")
            values = [float(row["prediction"])]
        else:
            values = [float(row[k]) for k in COLUMNS[3:8]]
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("Non-finite or negative forecast value")
        if point_only:
            prediction = values[0]
            reference = lower = upper = priority = None
        else:
            prediction, reference, lower, upper, priority = values
            if not lower <= prediction <= upper:
                raise ValueError("Invalid interval bounds")
        expected_status = "cold_start_zero_baseline" if route in cold_routes else "ok"
        if row["status"] != expected_status or (
            route in cold_routes and prediction != 0
        ):
            raise ValueError("Inconsistent baseline status")
        cells[key] = Cell(prediction, reference, lower, upper, priority, row["status"])
    if not cells:
        raise ValueError("Empty forecast CSV")
    stamps = [key[1] for key in cells]
    if not isinstance(metadata["limitations"], list):
        raise ValueError("Invalid limitations")
    limitations = tuple(metadata["limitations"])
    if not all(isinstance(v, str) for v in limitations):
        raise ValueError("Invalid limitations")
    return Snapshot(
        run_id=receipt["forecast_run_id"],
        model_version=hashes["model.joblib"],
        dataset_version=digest(
            json.dumps(manifest["source_checksums"], sort_keys=True).encode()
        ),
        csv_sha256=hashes["forecast.csv"],
        imported_at=receipt["imported_at"],
        routes=routes,
        cold_routes=cold_routes,
        start=min(stamps),
        end=max(stamps) + timedelta(hours=1),
        interval_method=interval_method,
        cells=MappingProxyType(cells),
        limitations=limitations,
    )
