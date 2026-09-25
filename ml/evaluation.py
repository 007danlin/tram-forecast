"""Temporal model selection, final holdout evaluation, and slice reporting."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from ml.baselines import BlockMeanBaseline, ComparableWeeksMedianBaseline, PreviousWeekdayBaseline
from ml.data import load_organizer_labels
from ml.factors import weather_coverage
from ml.metrics import regression_metrics
from ml.model import HGBT_FIXED_PARAMETERS, HourlyGradientBoostingModel, build_hgbt_model
from ml.settings import (
    FINAL_HOLDOUT,
    KEY_COLUMNS,
    MODEL_SCHEMA_VERSION,
    RANDOM_SEED,
    SELECTION_FOLDS,
    TARGET_COLUMN,
    TemporalFold,
)


ModelFactory = Callable[[], object]


MODEL_FACTORIES: dict[str, ModelFactory] = {
    "block_mean": BlockMeanBaseline,
    "previous_weekday": PreviousWeekdayBaseline,
    "median_comparable_weeks": ComparableWeeksMedianBaseline,
    "calendar_hgbt": lambda: build_hgbt_model("calendar_hgbt"),
    "lagged_hgbt": lambda: build_hgbt_model("lagged_hgbt"),
    "calendar_holiday_hgbt": lambda: build_hgbt_model("calendar_holiday_hgbt"),
    "competition_weather_hgbt": lambda: build_hgbt_model("competition_weather_hgbt"),
}

MODEL_PARAMETERS: dict[str, dict[str, object]] = {
    "block_mean": {"hour_block_width": 8},
    "previous_weekday": {"lookback": "latest fitted route-hour-weekday"},
    "median_comparable_weeks": {"weeks": 8},
    "calendar_hgbt": {
        "algorithm": "HistGradientBoostingRegressor",
        "include_lags": False,
        **HGBT_FIXED_PARAMETERS,
        "max_iter": 220,
        "max_leaf_nodes": 31,
    },
    "lagged_hgbt": {
        "algorithm": "HistGradientBoostingRegressor",
        "include_lags": True,
        "lags_days": [7, 14, 21, 28],
        **HGBT_FIXED_PARAMETERS,
        "max_iter": 220,
        "max_leaf_nodes": 31,
    },
    "calendar_holiday_hgbt": {
        "algorithm": "HistGradientBoostingRegressor",
        "include_lags": False,
        "include_official_calendar": True,
        "information_mode": "operational",
        **HGBT_FIXED_PARAMETERS,
        "max_iter": 220,
        "max_leaf_nodes": 31,
    },
    "competition_weather_hgbt": {
        "algorithm": "HistGradientBoostingRegressor",
        "include_lags": False,
        "include_official_calendar": True,
        "include_weather": True,
        "information_mode": "competition_retro",
        **HGBT_FIXED_PARAMETERS,
        "max_iter": 220,
        "max_leaf_nodes": 31,
    },
}

MODEL_HYPOTHESES = {
    "block_mean": "Three broad hourly blocks provide a reproducible floor.",
    "previous_weekday": "The latest comparable weekday improves over broad blocks.",
    "median_comparable_weeks": "A robust eight-week weekday median reduces one-week noise.",
    "calendar_hgbt": "A compact nonlinear calendar model captures route and seasonal interactions.",
    "lagged_hgbt": "Leakage-safe recursive weekly lags improve the calendar model.",
    "calendar_holiday_hgbt": "Verified 2025 days off improve over weekend-only calendar features.",
    "competition_weather_hgbt": "ERA5 reanalysis improves the calendar-holiday model in competition-retrospective mode.",
}

IMPORTANT_LOG_SLICES = (
    "route",
    "hour",
    "weekpart",
    "daypart",
    "flow_band",
    "horizon_bucket",
    "horizon_week",
    "status",
)


def _merge_actual_prediction(actual: pd.DataFrame, predicted: pd.DataFrame) -> pd.DataFrame:
    merged = actual.merge(
        predicted[[*KEY_COLUMNS, "prediction", "status"]],
        on=list(KEY_COLUMNS),
        how="left",
        validate="one_to_one",
    )
    if merged["prediction"].isna().any():
        raise ValueError("Prediction does not cover the complete validation grid")
    if not np.isfinite(merged["prediction"]).all() or (merged["prediction"] < 0).any():
        raise ValueError("Prediction contains invalid values")
    merged["horizon_day"] = (merged["date"] - merged["date"].min()).dt.days + 1
    merged["horizon_week"] = ((merged["horizon_day"] - 1) // 7) + 1
    merged["horizon_bucket"] = pd.cut(
        merged["horizon_day"],
        bins=[0, 7, 30, 61, np.inf],
        labels=["days_1_7", "days_8_30", "days_31_61", "days_62_plus"],
    ).astype("string")
    merged["dow"] = merged["date"].dt.dayofweek
    merged["weekpart"] = np.where(merged["dow"] >= 5, "weekend", "weekday")
    merged["daypart"] = np.where(merged["hour"].isin([7, 8, 9, 16, 17, 18, 19]), "peak", "offpeak")
    merged["flow_band"] = pd.cut(
        merged[TARGET_COLUMN],
        bins=[-0.1, 0, 10, 100, 500, 1000, 2500, np.inf],
        labels=["zero", "1_10", "11_100", "101_500", "501_1000", "1001_2500", "2501_plus"],
    ).astype("string")
    return merged


def _metric_record(frame: pd.DataFrame, slice_name: str, slice_value: object) -> dict[str, object]:
    return {
        "slice": slice_name,
        "value": str(slice_value),
        **regression_metrics(frame[TARGET_COLUMN], frame["prediction"]),
    }


def slice_metrics(frame: pd.DataFrame) -> list[dict[str, object]]:
    records = [_metric_record(frame, "overall", "all")]
    for column in (
        "route",
        "hour",
        "weekpart",
        "daypart",
        "flow_band",
        "horizon_bucket",
        "horizon_week",
        "status",
    ):
        for value, part in frame.groupby(column, observed=True, sort=True):
            records.append(_metric_record(part, column, value))
    return records


def evaluate_model(
    dataset_dir: str | Path,
    fold: TemporalFold,
    model_name: str,
    factors: pd.DataFrame | None = None,
) -> tuple[dict[str, object], pd.DataFrame]:
    if model_name not in MODEL_FACTORIES:
        raise KeyError(f"Unknown model: {model_name}")
    target = load_organizer_labels(dataset_dir, fold.train_start, fold.val_end)
    history = target[target["date"].between(pd.Timestamp(fold.train_start), pd.Timestamp(fold.train_end))].copy()
    actual = target[target["date"].between(pd.Timestamp(fold.val_start), pd.Timestamp(fold.val_end))].copy()
    model = MODEL_FACTORIES[model_name]()
    started = time.perf_counter()
    if isinstance(model, HourlyGradientBoostingModel):
        model.fit(history, factors=factors)
        predicted = model.predict(fold.val_start, fold.val_end, factors=factors)
        information_mode = model.information_mode
        factor_groups = [
            factor
            for factor, enabled in (
                ("F01_official_calendar", model.include_official_calendar),
                ("F02_weather_reanalysis", model.include_weather),
            )
            if enabled
        ]
    else:
        model.fit(history)
        predicted = model.predict(fold.val_start, fold.val_end)
        information_mode = "operational"
        factor_groups = []
    elapsed = time.perf_counter() - started
    merged = _merge_actual_prediction(actual, predicted)
    return {
        "experiment_id": f"{fold.name}__{model_name}",
        "hypothesis": MODEL_HYPOTHESES[model_name],
        "change": model_name,
        "information_mode": information_mode,
        "factor_groups": factor_groups,
        "factor_coverage": (
            weather_coverage(factors, fold.train_start, fold.val_end)
            if "F02_weather_reanalysis" in factor_groups and factors is not None
            else None
        ),
        "model_schema_version": MODEL_SCHEMA_VERSION,
        "random_seed": RANDOM_SEED,
        "parameters": MODEL_PARAMETERS[model_name],
        "fold": asdict(fold),
        "elapsed_seconds": elapsed,
        "metrics": slice_metrics(merged),
    }, merged


def _combined_metrics(predictions: list[pd.DataFrame]) -> dict[str, float | int | None]:
    combined = pd.concat(predictions, ignore_index=True)
    return regression_metrics(combined[TARGET_COLUMN], combined["prediction"])


def experiment_log_frame(report: dict[str, object]) -> pd.DataFrame:
    """Flatten the complete evaluation report into an auditable CSV journal."""
    rows: list[dict[str, object]] = []
    for experiment in report["experiments"]:
        fold = experiment["fold"]
        metrics = experiment["metrics"]
        overall = next(metric for metric in metrics if metric["slice"] == "overall")
        slice_results: dict[str, dict[str, dict[str, float | int | None]]] = {}
        for metric in metrics:
            slice_name = metric["slice"]
            if slice_name not in IMPORTANT_LOG_SLICES:
                continue
            slice_results.setdefault(slice_name, {})[metric["value"]] = {
                key: metric[key]
                for key in ("wape_score", "wape", "mae", "rows", "sum_y")
            }
        rows.append(
            {
                "experiment_id": experiment["experiment_id"],
                "role": fold["role"],
                "hypothesis": experiment["hypothesis"],
                "change": experiment["change"],
                "information_mode": experiment["information_mode"],
                "factor_groups_json": json.dumps(
                    experiment["factor_groups"], ensure_ascii=False, separators=(",", ":")
                ),
                "factor_coverage_json": json.dumps(
                    experiment["factor_coverage"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ) if experiment["factor_coverage"] is not None else "",
                "model_schema_version": experiment["model_schema_version"],
                "random_seed": experiment["random_seed"],
                "parameters_json": json.dumps(
                    experiment["parameters"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
                "train_start": fold["train_start"],
                "train_end": fold["train_end"],
                "validation_start": fold["val_start"],
                "validation_end": fold["val_end"],
                "wape_score": overall["wape_score"],
                "wape": overall["wape"],
                "mae": overall["mae"],
                "rows": overall["rows"],
                "sum_y": overall["sum_y"],
                "elapsed_seconds": experiment["elapsed_seconds"],
                "important_slices_json": json.dumps(
                    slice_results,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "decision": experiment["decision"],
            }
        )
    return pd.DataFrame(rows)


def run_full_evaluation(
    dataset_dir: str | Path,
    factors: pd.DataFrame | None = None,
) -> tuple[dict[str, object], dict[str, list[pd.DataFrame]]]:
    """Select on early folds, then open the final holdout once for the chosen approach."""
    enabled_models = [name for name in MODEL_FACTORIES if name != "competition_weather_hgbt" or factors is not None]
    experiments: list[dict[str, object]] = []
    selection_predictions: dict[str, list[pd.DataFrame]] = {name: [] for name in enabled_models}
    for model_name in enabled_models:
        for fold in SELECTION_FOLDS:
            record, prediction = evaluate_model(dataset_dir, fold, model_name, factors=factors)
            experiments.append(record)
            selection_predictions[model_name].append(prediction)

    selection_summary = {name: _combined_metrics(parts) for name, parts in selection_predictions.items()}
    selected_model = max(
        selection_summary,
        key=lambda name: float(selection_summary[name]["wape_score"] or 0.0),
    )
    for experiment in experiments:
        model_name = experiment["change"]
        if model_name == selected_model:
            experiment["decision"] = "selected_on_combined_folds"
        elif model_name == "block_mean":
            experiment["decision"] = "floor_rejected"
        elif model_name in {"previous_weekday", "median_comparable_weeks"}:
            experiment["decision"] = "benchmark_retained"
        else:
            experiment["decision"] = "rejected"
    chosen_residuals = np.concatenate(
        [
            np.abs(
                part.loc[part["status"] == "ok", TARGET_COLUMN].to_numpy(dtype=float)
                - part.loc[part["status"] == "ok", "prediction"].to_numpy(dtype=float)
            )
            for part in selection_predictions[selected_model]
        ]
    )
    interval_absolute_error_q90 = float(np.quantile(chosen_residuals, 0.90))

    holdout_models = ("block_mean", "previous_weekday", "median_comparable_weeks", selected_model)
    holdout_predictions: dict[str, list[pd.DataFrame]] = {}
    seen: set[str] = set()
    for model_name in holdout_models:
        if model_name in seen:
            continue
        seen.add(model_name)
        record, prediction = evaluate_model(dataset_dir, FINAL_HOLDOUT, model_name, factors=factors)
        record["decision"] = "evaluated_once_after_selection"
        experiments.append(record)
        holdout_predictions[model_name] = [prediction]

    chosen_holdout = holdout_predictions[selected_model][0]
    supported_holdout = chosen_holdout[chosen_holdout["status"] == "ok"]
    lower = np.maximum(supported_holdout["prediction"].to_numpy() - interval_absolute_error_q90, 0.0)
    upper = supported_holdout["prediction"].to_numpy() + interval_absolute_error_q90
    y = supported_holdout[TARGET_COLUMN].to_numpy()
    interval_coverage = float(np.mean((y >= lower) & (y <= upper)))

    report = {
        "protocol": {
            "selection_folds": [asdict(fold) for fold in SELECTION_FOLDS],
            "final_holdout": asdict(FINAL_HOLDOUT),
            "holdout_opened_after_selection": True,
            "metric": "global WAPE-score = max(0, 1 - sum(abs(y-yhat))/sum(y))",
            "random_split": False,
            "model_schema_version": MODEL_SCHEMA_VERSION,
            "random_seed": RANDOM_SEED,
            "primary_61_day_validation": asdict(FINAL_HOLDOUT),
            "future_target_used_within_horizon": False,
        },
        "selection_summary": selection_summary,
        "selected_model": selected_model,
        "interval": {
            "method": "symmetric absolute-residual quantile calibrated on selection folds",
            "nominal_coverage": 0.90,
            "absolute_error_q90": interval_absolute_error_q90,
            "final_holdout_coverage": interval_coverage,
            "coverage_scope": "supported routes only; cold-start route 5 reported separately",
        },
        "experiments": experiments,
        "external_factors": {
            "calendar": {"status": "integrated", "scope": "hour, weekday, weekend, month, annual phase"},
            "F01_official_calendar": {
                "status": "validated",
                "information_mode": "operational",
                "decision": "selected" if selected_model == "calendar_holiday_hgbt" else "not selected on combined folds",
            },
            "F02_weather_reanalysis": {
                "status": "validated" if factors is not None else "candidate",
                "information_mode": "competition_retro",
                "decision": (
                    "selected" if selected_model == "competition_weather_hgbt"
                    else "not selected on combined folds" if factors is not None
                    else "normalized snapshot not supplied"
                ),
                "operational_status": "not integrated; no matching as-of forecast-run archive in this experiment",
            },
            "events_and_closures": {"status": "candidate", "reason": "No versioned historical archive supplied."},
            "traffic": {"status": "candidate", "reason": "No historical route-linked series supplied."},
        },
    }
    all_predictions = {**selection_predictions, **{f"holdout:{k}": v for k, v in holdout_predictions.items()}}
    return report, all_predictions
