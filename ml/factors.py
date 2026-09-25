"""Versioned external-factor preparation and validation for ML experiments."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


CALENDAR_SOURCE_URL = "https://government.ru/docs/all/155500/"
WEATHER_SOURCE_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_REQUIRED_COLUMNS = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "snowfall",
    "wind_speed_10m",
    "wind_gusts_10m",
)
WEATHER_OPTIONAL_COLUMNS = ("snow_depth",)
WEATHER_UNITS = {"time": "iso8601", "temperature_2m": "°C", "apparent_temperature": "°C",
                 "precipitation": "mm", "snowfall": "cm", "snow_depth": "m",
                 "wind_speed_10m": "km/h", "wind_gusts_10m": "km/h"}
NORMALIZER_VERSION = "open-meteo-normalizer-2"
ALIGNMENTS = ("legacy_timestamp_v1", "next_hour_accumulation_v2")
WEATHER_MODEL_COLUMNS = (
    *WEATHER_REQUIRED_COLUMNS,
    "near_freezing",
    "freeze_transition",
    "precipitation_6h",
    "is_wet",
    "is_snowing",
)
HOLIDAY_MODEL_COLUMNS = (
    "is_day_off",
    "is_public_holiday",
    "is_transferred_day_off",
    "is_working_weekend",
    "is_day_before_holiday",
    "is_day_after_holiday",
    "day_off_streak",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def official_calendar_2025() -> pd.DataFrame:
    """Return the verified 2025 Russian calendar without inferring other years."""
    dates = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    frame = pd.DataFrame({"date": dates})

    public_holidays = set(pd.date_range("2025-01-01", "2025-01-08")) | {
        pd.Timestamp("2025-02-23"),
        pd.Timestamp("2025-03-08"),
        pd.Timestamp("2025-05-01"),
        pd.Timestamp("2025-05-09"),
        pd.Timestamp("2025-06-12"),
        pd.Timestamp("2025-11-04"),
    }
    transferred_days_off = {
        pd.Timestamp("2025-05-02"),
        pd.Timestamp("2025-05-08"),
        pd.Timestamp("2025-06-13"),
        pd.Timestamp("2025-11-03"),
        pd.Timestamp("2025-12-31"),
    }
    working_weekends = {pd.Timestamp("2025-11-01")}
    special_holiday_dates = public_holidays | transferred_days_off

    weekend = frame["date"].dt.dayofweek >= 5
    frame["is_public_holiday"] = frame["date"].isin(public_holidays).astype("int8")
    frame["is_transferred_day_off"] = frame["date"].isin(transferred_days_off).astype("int8")
    frame["is_working_weekend"] = frame["date"].isin(working_weekends).astype("int8")
    frame["is_day_off"] = (
        (weekend & ~frame["date"].isin(working_weekends)) | frame["date"].isin(special_holiday_dates)
    ).astype("int8")
    frame["is_day_before_holiday"] = frame["date"].add(pd.Timedelta(days=1)).isin(special_holiday_dates).astype("int8")
    frame["is_day_after_holiday"] = frame["date"].sub(pd.Timedelta(days=1)).isin(special_holiday_dates).astype("int8")

    groups = frame["is_day_off"].ne(frame["is_day_off"].shift()).cumsum()
    streak = frame.groupby(groups)["is_day_off"].transform("size")
    frame["day_off_streak"] = np.where(frame["is_day_off"].eq(1), streak, 0).astype("int8")
    return frame


def add_official_calendar_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    dates = pd.to_datetime(result["date"]).dt.normalize()
    unsupported = sorted(set(dates.dt.year) - {2025})
    if unsupported:
        raise ValueError(f"Official calendar is only verified for 2025, received years: {unsupported}")
    result["date"] = dates
    result = result.merge(official_calendar_2025(), on="date", how="left", validate="many_to_one")
    if result[list(HOLIDAY_MODEL_COLUMNS)].isna().any().any():
        raise ValueError("Official calendar does not cover every requested date")
    return result


def normalize_open_meteo_snapshot(
    snapshot_path: str | Path,
    output_path: str | Path,
    manifest_path: str | Path,
    *,
    source_url: str,
    start: str | None = None,
    end: str | None = None,
    receipt_path: str | Path | None = None,
    alignment: str = "legacy_timestamp_v1",
) -> tuple[Path, Path]:
    """Validate one raw Open-Meteo JSON response and write a stable local table."""
    source = Path(snapshot_path)
    receipt = json.loads(Path(receipt_path).read_text()) if receipt_path else None
    if source.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Weather response exceeds 32 MiB")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Weather provider returned an error or invalid object")
    if alignment not in ALIGNMENTS or (start is None) != (end is None):
        raise ValueError("Invalid alignment or incomplete expected period")
    if alignment != ALIGNMENTS[0] and start is None:
        raise ValueError("Shifted accumulation requires explicit target start/end and a buffer day")
    if payload.get("timezone") != "Europe/Moscow" or payload.get("utc_offset_seconds") != 10_800:
        raise ValueError("Weather snapshot must use Europe/Moscow with UTC+03:00")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Weather snapshot has no hourly object")

    missing_columns = set(("time", *WEATHER_REQUIRED_COLUMNS)) - set(hourly)
    if missing_columns:
        raise ValueError(f"Weather snapshot misses required fields: {sorted(missing_columns)}")
    units = payload.get("hourly_units", {})
    if any(units.get(name) != WEATHER_UNITS[name] for name in ("time", *WEATHER_REQUIRED_COLUMNS)):
        raise ValueError("Unexpected or missing weather units")
    normalized = pd.DataFrame({name: hourly[name] for name in ("time", *WEATHER_REQUIRED_COLUMNS)})
    normalized = normalized.rename(columns={"time": "timestamp"})
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], format="%Y-%m-%dT%H:%M", errors="raise")
    if normalized["timestamp"].duplicated().any():
        raise ValueError("Weather snapshot contains duplicate timestamps")
    if normalized[list(WEATHER_REQUIRED_COLUMNS)].isna().any().any():
        missing = normalized[list(WEATHER_REQUIRED_COLUMNS)].isna().sum().to_dict()
        raise ValueError(f"Required weather fields contain nulls: {missing}")
    validate_weather_values(normalized, WEATHER_REQUIRED_COLUMNS)
    if normalized.empty:
        raise ValueError("Empty weather series")
    normalized = normalized.sort_values("timestamp", ignore_index=True)
    differences = normalized["timestamp"].diff().dropna()
    if not differences.eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Weather snapshot is not a continuous hourly series")

    if start is not None:
        first, last = pd.Timestamp(start), pd.Timestamp(end)
        if first > last or first != first.normalize() or last != last.normalize():
            raise ValueError("Expected weather bounds must be ordered calendar dates")
        buffer_days = int(alignment == ALIGNMENTS[1])
        raw_last = last + pd.Timedelta(days=buffer_days)
        if receipt is not None:
            requested = receipt.get("parameters", {})
            raw_last = pd.Timestamp(requested.get("end_date", raw_last))
            if requested.get("start_date") != start or raw_last < last + pd.Timedelta(days=buffer_days) or raw_last > last + pd.Timedelta(days=1):
                raise ValueError("Receipt bounds do not match target and optional buffer day")
        expected_raw = pd.date_range(first, raw_last + pd.Timedelta(hours=23), freq="h")
        if not normalized["timestamp"].equals(pd.Series(expected_raw)):
            raise ValueError("Weather timestamps do not exactly match the requested grid")
    excluded_optional: dict[str, str] = {}
    for column in WEATHER_OPTIONAL_COLUMNS:
        values = hourly.get(column)
        if values is None or all(value is None for value in values):
            excluded_optional[column] = "not available in selected Open-Meteo model; not imputed"
        elif len(values) != len(normalized) or any(value is None for value in values):
            excluded_optional[column] = "partial coverage; not imputed"
        else:
            if units.get(column) != WEATHER_UNITS[column]:
                raise ValueError(f"Unexpected weather unit: {column}")
            optional = pd.DataFrame({"timestamp": pd.to_datetime(hourly["time"]), column: values}).sort_values("timestamp", ignore_index=True)
            validate_weather_values(optional, (column,))
            normalized[column] = optional[column]
    if alignment == ALIGNMENTS[1]:
        for column in ("precipitation", "snowfall"):
            normalized[column] = normalized[column].shift(-1)
    if end is not None:
        normalized = normalized[normalized["timestamp"] < pd.Timestamp(end) + pd.Timedelta(days=1)].copy()
        validate_weather_values(normalized, WEATHER_REQUIRED_COLUMNS)
    fetched_at = None
    if receipt is not None:
        if receipt.get("raw_sha256") != sha256_file(source) or receipt.get("http_status") != 200:
            raise ValueError("Weather receipt does not match successful raw response")
        fetched_at = receipt["completed_at"]
        if datetime.fromisoformat(fetched_at).utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("Receipt completion must be UTC")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(destination, sep=";", index=False, encoding="utf-8", lineterminator="\n")

    manifest = {
        "source_id": "open_meteo_era5_moscow_2025",
        "model": "era5",
        "normalizer_version": NORMALIZER_VERSION,
        "alignment": alignment,
        "request_parameters": receipt.get("parameters") if receipt else None,
        "fetched_at": fetched_at,
        "issued_at": None,
        "available_at": None,
        "license_url": "https://open-meteo.com/en/terms",
        "terms_reviewed_on": "2026-09-25",
        "attribution": "Weather data by Open-Meteo, CC BY 4.0; ERA5 reanalysis",
        "source_url": source_url,
        "information_mode": "competition_retro",
        "description": "ERA5 reanalysis for one Moscow grid point; not a stop-level sensor measurement",
        "requested_coordinates": {"latitude": 55.7558, "longitude": 37.6173},
        "returned_coordinates": {"latitude": payload.get("latitude"), "longitude": payload.get("longitude")},
        "timezone": payload.get("timezone"),
        "utc_offset_seconds": payload.get("utc_offset_seconds"),
        "hourly_units": payload.get("hourly_units", {}),
        "period": {
            "start": str(normalized["timestamp"].min()),
            "end": str(normalized["timestamp"].max()),
            "rows": int(len(normalized)),
        },
        "required_columns": list(WEATHER_REQUIRED_COLUMNS),
        "excluded_optional_columns": excluded_optional,
        "raw_snapshot": {
            "filename": source.name,
            "sha256": sha256_file(source),
            "fetched_at": fetched_at,
            "file_mtime": datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat(),
            "fetched_at_status": "receipt" if receipt else "unknown; mtime is not acquisition time",
        },
        "normalized": {"filename": destination.name, "sha256": sha256_file(destination)},
    }
    manifest_destination = Path(manifest_path)
    manifest_destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination, manifest_destination


def validate_weather_values(frame: pd.DataFrame, columns) -> None:
    for column in columns:
        values = frame[column]
        if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values) or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"Weather field must contain finite numbers: {column}")
        if column not in ("temperature_2m", "apparent_temperature") and values.lt(0).any():
            raise ValueError(f"Weather field must be nonnegative: {column}")


def load_weather_factors(path: str | Path, columns: tuple[str, ...] = WEATHER_MODEL_COLUMNS) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=";")
    if set(columns) - set(WEATHER_MODEL_COLUMNS):
        raise ValueError("Unknown model weather columns")
    required = set(columns) & set(WEATHER_REQUIRED_COLUMNS)
    if set(columns) & {"near_freezing", "freeze_transition"}: required.add("temperature_2m")
    if set(columns) & {"is_wet", "precipitation_6h"}: required.add("precipitation")
    if "is_snowing" in columns: required.add("snowfall")
    missing = {"timestamp", *required} - set(frame.columns)
    if missing:
        raise ValueError(f"Normalized weather data misses columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    if frame.empty or frame["timestamp"].dt.tz is not None or not frame["timestamp"].eq(frame["timestamp"].dt.floor("h")).all():
        raise ValueError("Weather timestamps must be nonempty naive MSK hourly labels")
    validate_weather_values(frame, required)
    frame = frame.sort_values("timestamp", ignore_index=True)
    if frame["timestamp"].duplicated().any():
        raise ValueError("Normalized weather data contains duplicate timestamps")
    if frame[list(required)].isna().any().any():
        raise ValueError("Normalized weather data contains missing required values")
    if not frame["timestamp"].diff().dropna().eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Normalized weather data is not hourly-continuous")

    if "near_freezing" in columns:
        frame["near_freezing"] = frame["temperature_2m"].abs().le(1.5).astype("int8")
    if "freeze_transition" in columns:
        previous_temperature = frame["temperature_2m"].shift(1)
        frame["freeze_transition"] = (((previous_temperature < 0) & (frame["temperature_2m"] >= 0))
            | ((previous_temperature >= 0) & (frame["temperature_2m"] < 0))).astype("int8")
    if "precipitation_6h" in columns:
        frame["precipitation_6h"] = frame["precipitation"].rolling(6, min_periods=1).sum()
    if "is_wet" in columns:
        frame["is_wet"] = frame["precipitation"].gt(0).astype("int8")
    if "is_snowing" in columns:
        frame["is_snowing"] = frame["snowfall"].gt(0).astype("int8")
    return frame[["timestamp", *columns]]


def weather_coverage(frame: pd.DataFrame, start: str | pd.Timestamp, end: str | pd.Timestamp) -> dict[str, object]:
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize() + pd.Timedelta(hours=23)
    expected = pd.date_range(start_ts, end_ts, freq="h")
    available = frame[frame["timestamp"].between(start_ts, end_ts)]
    matched = available["timestamp"].isin(expected).sum()
    return {
        "expected_hours": int(len(expected)),
        "available_hours": int(matched),
        "coverage": float(matched / len(expected)) if len(expected) else None,
        "start": str(start_ts),
        "end": str(end_ts),
    }
