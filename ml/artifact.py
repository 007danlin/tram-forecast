"""Versioned local model artifact, inference output, and strict submission adapter."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.baselines import ComparableWeeksMedianBaseline
from ml.data import load_organizer_labels
from ml.model import HGBT_FIXED_PARAMETERS, HourlyGradientBoostingModel
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


def create_artifact(
    dataset_dir: str | Path,
    artifact_dir: str | Path,
    *,
    model_name: str,
    interval_absolute_error_q90: float,
) -> Path:
    root = Path(dataset_dir)
    destination = Path(artifact_dir)
    destination.mkdir(parents=True, exist_ok=True)
    if model_name not in {"calendar_hgbt", "lagged_hgbt"}:
        raise ValueError("Only fitted gradient-boosting candidates are artifact models")

    history = load_organizer_labels(root, FINAL_TRAIN_START, FINAL_TRAIN_END)
    model = HourlyGradientBoostingModel(include_lags=model_name == "lagged_hgbt").fit(history)
    reference = ComparableWeeksMedianBaseline().fit(history)
    supported_routes = list(model.supported_routes_)
    cold_start_routes = sorted(set(ROUTES) - set(supported_routes))
    payload = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model": model,
        "reference": reference,
        "interval_absolute_error_q90": float(interval_absolute_error_q90),
    }
    model_path = destination / "model.joblib"
    joblib.dump(payload, model_path, compress=3)

    metadata = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "target": "count(validation_result == 1) by route, calendar date and hour of tran_date_time",
        "unit": "successful_boardings",
        "grain": list(KEY_COLUMNS),
        "model_name": model_name,
        "random_seed": RANDOM_SEED,
        "model_parameters": {
            "include_lags": model.include_lags,
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
            "method": "symmetric absolute-residual q90 from pre-holdout selection folds",
            "absolute_error_q90": float(interval_absolute_error_q90),
        },
        "limitations": [
            "Target measures successful boardings, not onboard occupancy.",
            "No direction or stop-level target is available.",
            "Route 5 has no successful target observations in January-October 2025.",
            "Weather, events, closures and traffic are not used because versioned as-of archives were not supplied.",
            "Annual numeric forecasting is unsupported with ten months of history.",
        ],
        "dependencies": _versions(),
    }
    metadata_path = destination / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    feature_schema = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "keys": {"route": "int", "date": "YYYY-MM-DD", "hour": "int[0,23]"},
        "calendar_features": ["route", "hour", "weekday", "month", "is_weekend", "day_of_year_sin", "day_of_year_cos"],
        "lag_features": ["lag_7d", "lag_14d", "lag_21d", "lag_28d", "lag_mean_4w", "lag_median_4w", "recent_trend"] if model.include_lags else [],
        "lag_policy": "training uses shifted actual history; multi-step inference recursively uses prior predictions once actual lags are unavailable",
        "unavailable_inputs": ["input_date_time", "begin_date_time", "pass_route", "future actual weather"],
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
    manifest = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "files": {
            "model.joblib": sha256_file(model_path),
            "metadata.json": sha256_file(metadata_path),
            "feature-schema.json": sha256_file(feature_path),
        },
        "source_checksums": sources,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def load_artifact(artifact_dir: str | Path) -> tuple[dict, dict]:
    root = Path(artifact_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for filename, expected in manifest["files"].items():
        actual = sha256_file(root / filename)
        if actual != expected:
            raise ValueError(f"Artifact checksum mismatch: {filename}")
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    payload = joblib.load(root / "model.joblib")
    if payload.get("schema_version") != MODEL_SCHEMA_VERSION or metadata.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise ValueError("Unsupported model artifact schema")
    return payload, metadata


def predict_artifact(artifact_dir: str | Path, start: date | str, end: date | str) -> pd.DataFrame:
    payload, _ = load_artifact(artifact_dir)
    prediction = payload["model"].predict(start, end)
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
    values = merged["prediction"].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Submission predictions must be finite and nonnegative")
    merged["prediction"] = np.floor(values + 0.5).astype("int64")
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(destination, sep=";", index=False, encoding="utf-8", lineterminator="\n")
    return destination
