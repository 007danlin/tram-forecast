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
) -> tuple[Path, Path]:
    """Validate one raw Open-Meteo JSON response and write a stable local table."""
    source = Path(snapshot_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("timezone") != "Europe/Moscow" or payload.get("utc_offset_seconds") != 10_800:
        raise ValueError("Weather snapshot must use Europe/Moscow with UTC+03:00")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Weather snapshot has no hourly object")

    missing_columns = set(("time", *WEATHER_REQUIRED_COLUMNS)) - set(hourly)
    if missing_columns:
        raise ValueError(f"Weather snapshot misses required fields: {sorted(missing_columns)}")
    normalized = pd.DataFrame({name: hourly[name] for name in ("time", *WEATHER_REQUIRED_COLUMNS)})
    normalized = normalized.rename(columns={"time": "timestamp"})
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], format="%Y-%m-%dT%H:%M", errors="raise")
    if normalized["timestamp"].duplicated().any():
        raise ValueError("Weather snapshot contains duplicate timestamps")
    if normalized[list(WEATHER_REQUIRED_COLUMNS)].isna().any().any():
        missing = normalized[list(WEATHER_REQUIRED_COLUMNS)].isna().sum().to_dict()
        raise ValueError(f"Required weather fields contain nulls: {missing}")
    differences = normalized["timestamp"].sort_values().diff().dropna()
    if not differences.eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Weather snapshot is not a continuous hourly series")

    excluded_optional: dict[str, str] = {}
    for column in WEATHER_OPTIONAL_COLUMNS:
        values = hourly.get(column)
        if values is None or all(value is None for value in values):
            excluded_optional[column] = "not available in selected Open-Meteo model; not imputed"
        elif len(values) != len(normalized) or any(value is None for value in values):
            excluded_optional[column] = "partial coverage; not imputed"
        else:
            normalized[column] = values

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(destination, sep=";", index=False, encoding="utf-8", lineterminator="\n")

    manifest = {
        "source_id": "open_meteo_era5_moscow_2025",
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
            "fetched_at": datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat(),
        },
        "normalized": {"filename": destination.name, "sha256": sha256_file(destination)},
    }
    manifest_destination = Path(manifest_path)
    manifest_destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination, manifest_destination


def load_weather_factors(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=";")
    missing = set(("timestamp", *WEATHER_REQUIRED_COLUMNS)) - set(frame.columns)
    if missing:
        raise ValueError(f"Normalized weather data misses columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    frame = frame.sort_values("timestamp", ignore_index=True)
    if frame["timestamp"].duplicated().any():
        raise ValueError("Normalized weather data contains duplicate timestamps")
    if frame[list(WEATHER_REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("Normalized weather data contains missing required values")
    if not frame["timestamp"].diff().dropna().eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Normalized weather data is not hourly-continuous")

    frame["near_freezing"] = frame["temperature_2m"].abs().le(1.5).astype("int8")
    previous_temperature = frame["temperature_2m"].shift(1)
    frame["freeze_transition"] = (
        ((previous_temperature < 0) & (frame["temperature_2m"] >= 0))
        | ((previous_temperature >= 0) & (frame["temperature_2m"] < 0))
    ).astype("int8")
    frame["precipitation_6h"] = frame["precipitation"].rolling(6, min_periods=1).sum()
    frame["is_wet"] = frame["precipitation"].gt(0).astype("int8")
    frame["is_snowing"] = frame["snowfall"].gt(0).astype("int8")
    return frame[["timestamp", *WEATHER_MODEL_COLUMNS]]


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
