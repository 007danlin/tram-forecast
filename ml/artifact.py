"""Versioned local model artifact, inference output, and strict submission adapter."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import shutil
import tempfile
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.baselines import ComparableWeeksMedianBaseline
from ml.data import load_organizer_labels
from ml.experiment_config import normalize_config
from ml.factors import HOLIDAY_MODEL_COLUMNS, WEATHER_MODEL_COLUMNS, load_weather_factors
from ml.metrics import round_submission_predictions
from ml.model import HGBT_FIXED_PARAMETERS, build_hgbt_model
from ml.settings import (
    FINAL_TRAIN_END,
    FINAL_TRAIN_START,
    KEY_COLUMNS,
    MODEL_SCHEMA_VERSION,
    RANDOM_SEED,
    ROUTES,
    TARGET_COLUMN,
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versions() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scikit-learn", "joblib")}


def _write_artifact(
    dataset_dir: str | Path,
    artifact_dir: str | Path,
    *,
    model_name: str,
    interval_absolute_error_q90: float,
    factor_path: str | Path | None = None,
    experiment_config: dict | None = None,
    snapshot_manifest: dict | None = None,
) -> Path:
    root = Path(dataset_dir)
    destination = Path(artifact_dir)
    destination.mkdir(parents=True, exist_ok=True)
    history = load_organizer_labels(root, FINAL_TRAIN_START, FINAL_TRAIN_END)
    if not math.isfinite(interval_absolute_error_q90) or interval_absolute_error_q90 < 0:
        raise ValueError("Selection q90 must be finite and nonnegative")
    config = normalize_config(experiment_config) if experiment_config is not None else None
    model = build_hgbt_model(model_name, config)
    factors = load_weather_factors(factor_path, model.selected_weather_columns) if factor_path is not None and model.include_weather else None
    if config and model.include_weather:
        if snapshot_manifest is None or snapshot_manifest.get("alignment") != config["alignment"] or snapshot_manifest["normalized"]["sha256"] != sha256_file(factor_path):
            raise ValueError("Training snapshot differs from selected preprocessing/data")
    if model.include_weather and factors is None:
        raise ValueError("Selected competition-weather model requires --weather-factors")
    model.fit(history, factors=factors)
    reference = ComparableWeeksMedianBaseline().fit(history)
    supported_routes = list(model.supported_routes_)
    cold_start_routes = sorted(set(ROUTES) - set(supported_routes))
    payload = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model": model,
        "reference": reference,
        "factors": factors if model.include_weather else None,
        "interval_absolute_error_q90": float(interval_absolute_error_q90),
        "experiment_config": config,
        "snapshot_manifest": snapshot_manifest if model.include_weather else None,
    }
    model_path = destination / "model.joblib"
    joblib.dump(payload, model_path, compress=3)

    limitations = [
        "Target measures successful boardings, not onboard occupancy.",
        "No direction or stop-level target is available.",
        "Route 5 has no successful target observations in January-October 2025.",
        "Events, closures and traffic are not used because comparable versioned archives were not supplied.",
        "Annual numeric forecasting is unsupported with ten months of history.",
    ]
    if model.include_weather:
        limitations.append(
            "ERA5 weather is reanalysis at one Moscow grid point and is allowed only in competition-retrospective mode."
        )
    else:
        limitations.append("Weather is not used by this artifact.")

    metadata = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "target": "count(validation_result == 1) by route, calendar date and hour of tran_date_time",
        "unit": "successful_boardings",
        "grain": list(KEY_COLUMNS),
        "model_name": model_name,
        "experiment_config": config,
        "preprocessing": config["alignment"] if config else "legacy_timestamp_v1",
        "weather_columns": list(model.selected_weather_columns) if model.include_weather else [],
        "information_mode": model.information_mode,
        "factor_groups": [
            factor
            for factor, enabled in (
                ("F01_official_calendar", model.include_official_calendar),
                ("F02_weather_reanalysis", model.include_weather),
            )
            if enabled
        ],
        "random_seed": RANDOM_SEED,
        "model_parameters": {
            "include_lags": model.include_lags,
            "include_official_calendar": model.include_official_calendar,
            "include_weather": model.include_weather,
            **HGBT_FIXED_PARAMETERS,
            "max_iter": model.max_iter,
            "max_leaf_nodes": model.max_leaf_nodes,
        },
        "training_period": {"start": str(FINAL_TRAIN_START), "end": str(FINAL_TRAIN_END)},
        "supported_routes": supported_routes,
        "cold_start_routes": cold_start_routes,
        "cold_start_policy": "known organizer route with no successful history: zero baseline and explicit status",
        "unknown_route_policy": "unsupported",
        "raw_timezone": "unconfirmed; naive organizer calendar timestamps",
        "product_timezone_contract": "Europe/Moscow",
        "prediction": {"nonnegative": True, "rounded": False, "clipping": "max(raw_prediction, 0)"},
        "interval": {
            "method": "symmetric absolute-residual q90 from early selection folds",
            "absolute_error_q90": float(interval_absolute_error_q90),
        },
        "limitations": limitations,
        "dependencies": _versions(),
    }
    metadata_path = destination / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    feature_schema = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "keys": {"route": "int", "date": "YYYY-MM-DD", "hour": "int[0,23]"},
        "calendar_features": ["route", "hour", "weekday", "month", "is_weekend", "day_of_year_sin", "day_of_year_cos"],
        "official_calendar_features": list(HOLIDAY_MODEL_COLUMNS) if model.include_official_calendar else [],
        "weather_features": list(model.selected_weather_columns) if model.include_weather else [],
        "experiment_config": config,
        "preprocessing": config["alignment"] if config else "legacy_timestamp_v1",
        "information_mode": model.information_mode,
        "lag_features": ["lag_7d", "lag_14d", "lag_21d", "lag_28d", "lag_mean_4w", "lag_median_4w", "recent_trend"] if model.include_lags else [],
        "lag_policy": "training uses shifted actual history; multi-step inference recursively uses prior predictions once actual lags are unavailable",
        "unavailable_inputs": [
            "input_date_time",
            "begin_date_time",
            "pass_route",
            "future target y",
            *(("future actual weather",) if not model.include_weather else ()),
        ],
    }
    feature_path = destination / "feature-schema.json"
    feature_path.write_text(json.dumps(feature_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_paths = {
        "README.md": root / "README.md",
        "train.csv": root / "train.csv",
        "test.csv": root / "test.csv",
        "labels_day_train.csv": root / "labels" / "labels_day_train.csv",
        "labels_day_test.csv": root / "labels" / "labels_day_test.csv",
        "test_submission.csv": root / "test_submission.csv",
    }
    sources = {name: sha256_file(path) for name, path in source_paths.items()}
    factor_sources = {}
    if model.include_weather and factor_path is not None:
        factor_source_path = Path(factor_path)
        factor_sources[factor_source_path.name] = sha256_file(factor_source_path)
    manifest = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "files": {
            "model.joblib": sha256_file(model_path),
            "metadata.json": sha256_file(metadata_path),
            "feature-schema.json": sha256_file(feature_path),
        },
        "source_checksums": sources,
        "factor_checksums": factor_sources,
        "snapshot_manifest": snapshot_manifest if model.include_weather else None,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def create_artifact(dataset_dir, artifact_dir, *, model_name, interval_absolute_error_q90,
                    factor_path=None, experiment_config=None, snapshot_manifest=None):
    destination = Path(artifact_dir)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Artifact exists; use a new release directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ml-artifact-", dir=destination.parent))
    try:
        _write_artifact(dataset_dir, temporary, model_name=model_name,
                        interval_absolute_error_q90=interval_absolute_error_q90, factor_path=factor_path,
                        experiment_config=experiment_config, snapshot_manifest=snapshot_manifest)
        load_artifact(temporary)
        if destination.exists():
            raise ValueError("Artifact appeared during training; refusing overwrite")
        temporary.rename(destination)
        return destination
    finally:
        if temporary.exists(): shutil.rmtree(temporary)


def load_artifact(artifact_dir: str | Path) -> tuple[dict, dict]:
    root = Path(artifact_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MODEL_SCHEMA_VERSION or set(manifest.get("files", {})) != {"model.joblib", "metadata.json", "feature-schema.json"}:
        raise ValueError("Unexpected model manifest; handoff supports exactly three model files")
    for filename, expected in manifest["files"].items():
        actual = sha256_file(root / filename)
        if actual != expected:
            raise ValueError(f"Artifact checksum mismatch: {filename}")
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    payload = joblib.load(root / "model.joblib")
    if payload.get("schema_version") != MODEL_SCHEMA_VERSION or metadata.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise ValueError("Unsupported model artifact schema")
    features = json.loads((root / "feature-schema.json").read_text())
    config = metadata.get("experiment_config")
    if config is not None:
        config = normalize_config(config)
        if payload.get("experiment_config") != config or features.get("experiment_config") != config or features["weather_features"] != config["weather_columns"] or metadata["model_name"] != config["model_name"]:
            raise ValueError("Artifact experiment configuration mismatch")
        if list(payload["model"].selected_weather_columns) != config["weather_columns"]:
            raise ValueError("Serialized model uses different weather columns")
        if payload["interval_absolute_error_q90"] != metadata["interval"]["absolute_error_q90"]:
            raise ValueError("Artifact interval differs from selection q90")
    return payload, metadata


def predict_artifact(artifact_dir: str | Path, start: date | str, end: date | str) -> pd.DataFrame:
    payload, _ = load_artifact(artifact_dir)
    prediction = payload["model"].predict(start, end, factors=payload.get("factors"))
    reference = payload["reference"].predict(start, end).rename(columns={"prediction": "reference_value"})
    result = prediction.merge(reference[[*KEY_COLUMNS, "reference_value"]], on=list(KEY_COLUMNS), validate="one_to_one")
    q90 = float(payload["interval_absolute_error_q90"])
    result["lower_90"] = np.maximum(result["prediction"] - q90, 0.0)
    result["upper_90"] = result["prediction"] + q90
    result["priority_score"] = np.maximum(result["prediction"] - result["reference_value"], 0.0)
    return result[[*KEY_COLUMNS, "prediction", "reference_value", "lower_90", "upper_90", "priority_score", "status"]]


def write_submission(prediction: pd.DataFrame, template_path: str | Path, output_path: str | Path) -> Path:
    template = pd.read_csv(template_path, sep=";")
    expected_columns = ["route", "date", "hour", "prediction"]
    if list(template.columns) != expected_columns:
        raise ValueError(f"Unexpected submission columns: {list(template.columns)}")
    if template.duplicated(list(KEY_COLUMNS)).any():
        raise ValueError("Submission template contains duplicate keys")
    template["date"] = pd.to_datetime(template["date"], format="%Y-%m-%d", errors="raise")
    data = prediction.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    merged = template.drop(columns="prediction").merge(
        data[[*KEY_COLUMNS, "prediction"]], on=list(KEY_COLUMNS), how="left", validate="one_to_one"
    )
    if len(merged) != len(template) or merged["prediction"].isna().any():
        raise ValueError("Prediction does not match every submission template key")
    merged["prediction"] = round_submission_predictions(merged["prediction"])
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(destination, sep=";", index=False, encoding="utf-8", lineterminator="\n")
    return destination


def submission_preflight(output_path: str | Path, template_path: str | Path) -> dict[str, object]:
    output = Path(output_path)
    submission = pd.read_csv(output, sep=";")
    template = pd.read_csv(template_path, sep=";")
    keys = list(KEY_COLUMNS)
    expected_columns = [*keys, "prediction"]
    prediction_source = submission["prediction"] if "prediction" in submission else pd.Series(np.nan, index=submission.index)
    date_source = submission["date"] if "date" in submission else pd.Series(pd.NaT, index=submission.index)
    route_source = submission["route"] if "route" in submission else pd.Series(np.nan, index=submission.index)
    hour_source = submission["hour"] if "hour" in submission else pd.Series(np.nan, index=submission.index)
    numeric_prediction = pd.to_numeric(prediction_source, errors="coerce")
    numeric_route = pd.to_numeric(route_source, errors="coerce")
    numeric_hour = pd.to_numeric(hour_source, errors="coerce")
    date_values = pd.to_datetime(date_source, format="%Y-%m-%d", errors="coerce")
    exact_keys = (
        all(column in submission and column in template for column in keys)
        and len(submission) == len(template)
        and submission[keys].equals(template[keys])
    )
    checks = {
        "columns_exact": list(submission.columns) == expected_columns,
        "row_count_exact": len(submission) == 14_640,
        "template_keys_and_order_exact": exact_keys,
        "duplicate_keys": int(submission.duplicated(keys).sum()) if all(column in submission for column in keys) else None,
        "null_cells": int(submission.isna().sum().sum()),
        "finite_predictions": bool(np.isfinite(numeric_prediction).all()),
        "nonnegative_predictions": bool(numeric_prediction.ge(0).all()),
        "integer_predictions": bool(numeric_prediction.mod(1).eq(0).all()),
        "dates_valid": bool(date_values.notna().all()),
        "date_min": date_values.min().strftime("%Y-%m-%d") if date_values.notna().any() else None,
        "date_max": date_values.max().strftime("%Y-%m-%d") if date_values.notna().any() else None,
        "hours_valid": bool(numeric_hour.notna().all() and numeric_hour.mod(1).eq(0).all() and numeric_hour.between(0, 23).all()),
        "routes_valid": bool(numeric_route.notna().all() and numeric_route.mod(1).eq(0).all()),
        "routes": sorted(numeric_route.dropna().astype(int).unique().tolist()),
    }
    passed = (
        checks["columns_exact"]
        and checks["row_count_exact"]
        and checks["template_keys_and_order_exact"]
        and checks["duplicate_keys"] == 0
        and checks["null_cells"] == 0
        and checks["finite_predictions"]
        and checks["nonnegative_predictions"]
        and checks["integer_predictions"]
        and checks["dates_valid"]
        and checks["date_min"] == "2025-11-01"
        and checks["date_max"] == "2025-12-31"
        and checks["hours_valid"]
        and checks["routes_valid"]
        and checks["routes"] == list(ROUTES)
    )
    return {
        "passed": bool(passed),
        "file": output.name,
        "sha256": sha256_file(output),
        "rounding_policy": "floor(x + 0.5) at submission export only",
        "checks": checks,
    }
