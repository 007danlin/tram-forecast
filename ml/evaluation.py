"""Temporal model selection, reused final validation, and slice reporting."""

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
from ml.experiment_config import normalize_config
from ml.factors import weather_coverage
from ml.metrics import regression_metrics, round_submission_predictions
from ml.model import HGBT_FIXED_PARAMETERS, HourlyGradientBoostingModel, build_hgbt_model
from ml.qa import apply_training_mask, training_mask_summary
from ml.settings import (
    FINAL_VALIDATION,
    KEY_COLUMNS,
    MODELED_ROUTES,
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
    "calendar_interaction_squared_hgbt": lambda: build_hgbt_model("calendar_interaction_squared_hgbt"),
    "calendar_interaction_ensemble": lambda: build_hgbt_model("calendar_interaction_ensemble"),
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
    "calendar_interaction_squared_hgbt": {
        "algorithm": "HistGradientBoostingRegressor",
        "loss": "squared_error",
        "recency_half_life_days": 90,
        "interaction_categories": ["route_hour", "route_dow", "hour_dow", "week"],
        "learning_rate": 0.05,
        "max_iter": 300,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 24,
        "l2_regularization": 1.0,
    },
    "calendar_interaction_ensemble": {
        "components": ["calendar_holiday_hgbt", "calendar_interaction_squared_hgbt"],
        "weights": [0.425, 0.575],
        "output_scale": 0.96,
        "selection_grid": {"weight_step": 0.025, "scale_step": 0.01},
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
    "calendar_interaction_squared_hgbt": (
        "Recency weighting and explicit route-hour/day interactions capture changing demand levels."
    ),
    "calendar_interaction_ensemble": (
        "A fixed blend of robust absolute-loss calendar predictions and interaction-sensitive squared-loss "
        "predictions reduces complementary errors."
    ),
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
    merged["prediction_submission"] = round_submission_predictions(merged["prediction"])
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
    raw = regression_metrics(frame[TARGET_COLUMN], frame["prediction"])
    submission = regression_metrics(frame[TARGET_COLUMN], frame["prediction_submission"])
    return {
        "slice": slice_name,
        "value": str(slice_value),
        **raw,
        **{f"submission_{key}": value for key, value in submission.items()},
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
    experiment_config: dict | None = None,
    training_mask: dict[str, object] | None = None,
) -> tuple[dict[str, object], pd.DataFrame]:
    if model_name not in MODEL_FACTORIES:
        raise KeyError(f"Unknown model: {model_name}")
    target = load_organizer_labels(
        dataset_dir,
        fold.train_start,
        fold.val_end,
        routes=MODELED_ROUTES,
    )
    history = target[target["date"].between(pd.Timestamp(fold.train_start), pd.Timestamp(fold.train_end))].copy()
    actual = target[target["date"].between(pd.Timestamp(fold.val_start), pd.Timestamp(fold.val_end))].copy()
    mask_summary = None
    if training_mask is not None:
        mask_summary = training_mask_summary(history, training_mask)
        history = apply_training_mask(history, training_mask)
        history = history[history["training_included"]].copy()
    model = build_hgbt_model(model_name, experiment_config) if experiment_config is not None else MODEL_FACTORIES[model_name]()
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
        "experiment_id": f"{fold.name}__{experiment_config['id'] if experiment_config else model_name}",
        "config": experiment_config,
        "validation_days": (fold.val_end - fold.val_start).days + 1,
        "days_1_61_metrics": slice_metrics(merged[merged["horizon_day"] <= 61]),
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
        "parameters": {**MODEL_PARAMETERS[model_name], **({"experiment_config": experiment_config} if experiment_config else {})},
        "training_mask": (
            {
                "mask_id": training_mask["mask_id"],
                "sha256": training_mask["sha256"],
                "summary": mask_summary,
            }
            if training_mask is not None
            else None
        ),
        "fold": asdict(fold),
        "elapsed_seconds": elapsed,
        "metrics": slice_metrics(merged),
    }, merged


def _combined_metrics(predictions: list[pd.DataFrame]) -> dict[str, float | int | None]:
    combined = pd.concat(predictions, ignore_index=True)
    raw = regression_metrics(combined[TARGET_COLUMN], combined["prediction"])
    submission = regression_metrics(combined[TARGET_COLUMN], combined["prediction_submission"])
    return {**raw, **{f"submission_{key}": value for key, value in submission.items()}}


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
                for key in (
                    "wape_score",
                    "wape",
                    "mae",
                    "submission_wape_score",
                    "submission_wape",
                    "submission_mae",
                    "rows",
                    "sum_y",
                )
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
                "submission_wape_score": overall["submission_wape_score"],
                "submission_wape": overall["submission_wape"],
                "submission_mae": overall["submission_mae"],
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
    """Select on early folds, then report the reused September-October validation window."""
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
        key=lambda name: float(selection_summary[name]["submission_wape_score"] or 0.0),
    )
    for experiment in experiments:
        model_name = experiment["change"]
        if model_name == selected_model:
            experiment["decision"] = "selected_on_combined_folds_submission_rounded"
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

    validation_models = ("block_mean", "previous_weekday", "median_comparable_weeks", selected_model)
    validation_predictions: dict[str, list[pd.DataFrame]] = {}
    seen: set[str] = set()
    for model_name in validation_models:
        if model_name in seen:
            continue
        seen.add(model_name)
        record, prediction = evaluate_model(dataset_dir, FINAL_VALIDATION, model_name, factors=factors)
        record["decision"] = "evaluated_on_reused_validation_after_current_run_selection"
        experiments.append(record)
        validation_predictions[model_name] = [prediction]

    chosen_validation = validation_predictions[selected_model][0]
    supported_validation = chosen_validation[chosen_validation["status"] == "ok"]
    lower = np.maximum(supported_validation["prediction"].to_numpy() - interval_absolute_error_q90, 0.0)
    upper = supported_validation["prediction"].to_numpy() + interval_absolute_error_q90
    y = supported_validation[TARGET_COLUMN].to_numpy()
    interval_coverage = float(np.mean((y >= lower) & (y <= upper)))

    report = {
        "protocol": {
            "selection_folds": [asdict(fold) for fold in SELECTION_FOLDS],
            "reused_final_validation": asdict(FINAL_VALIDATION),
            "period_is_pristine_holdout": False,
            "period_reuse_history": {
                "previous_pull_request": 2,
                "previous_model": "calendar_hgbt",
                "previous_reported_wape_score_raw": 0.8287,
                "note": "September-October was evaluated before this addendum; current model selection still uses only the earlier selection folds.",
            },
            "metric": "global WAPE-score = max(0, 1 - sum(abs(y-yhat))/sum(y))",
            "selection_metric": "submission_wape_score after floor(prediction + 0.5)",
            "rounding_policy": "floor(x + 0.5); identical to submission export",
            "random_split": False,
            "model_schema_version": MODEL_SCHEMA_VERSION,
            "random_seed": RANDOM_SEED,
            "primary_61_day_validation": asdict(FINAL_VALIDATION),
            "future_target_used_within_horizon": False,
            "model_scope_routes": list(MODELED_ROUTES),
        },
        "selection_summary": selection_summary,
        "selected_model": selected_model,
        "interval": {
            "method": "symmetric absolute-residual quantile calibrated on selection folds",
            "nominal_coverage": 0.90,
            "absolute_error_q90": interval_absolute_error_q90,
            "reused_final_validation_coverage": interval_coverage,
            "coverage_scope": "nine-route model scope; route 5 is outside model evaluation",
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
    all_predictions = {
        **selection_predictions,
        **{f"reused_validation:{key}": value for key, value in validation_predictions.items()},
    }
    return report, all_predictions


def run_training_mask_comparison(
    dataset_dir: str | Path,
    training_mask: dict[str, object],
) -> dict[str, object]:
    """Compare one frozen model before/after cleaning on identical validation rows."""
    experiments: list[dict[str, object]] = []
    predictions: dict[str, list[pd.DataFrame]] = {"unmasked": [], "masked": []}
    folds = (*SELECTION_FOLDS, FINAL_VALIDATION)
    for fold in folds:
        raw_record, raw_prediction = evaluate_model(
            dataset_dir,
            fold,
            "calendar_holiday_hgbt",
        )
        raw_record["experiment_id"] = f"{fold.name}__target_unmasked"
        raw_record["hypothesis"] = "Keep the organizer target unchanged as the control."
        raw_record["change"] = "target_unmasked"
        raw_record["decision"] = "control"
        experiments.append(raw_record)
        predictions["unmasked"].append(raw_prediction)

        clean_record, clean_prediction = evaluate_model(
            dataset_dir,
            fold,
            "calendar_holiday_hgbt",
            training_mask=training_mask,
        )
        if not raw_prediction[[*KEY_COLUMNS, TARGET_COLUMN]].equals(
            clean_prediction[[*KEY_COLUMNS, TARGET_COLUMN]]
        ):
            raise ValueError("Training-mask comparison changed the evaluation keys or target")
        clean_record["experiment_id"] = f"{fold.name}__target_masked"
        clean_record["hypothesis"] = "A verified technological-validation mask improves training without changing evaluation rows."
        clean_record["change"] = "target_masked"
        clean_record["decision"] = "requires_owner_review"
        experiments.append(clean_record)
        predictions["masked"].append(clean_prediction)

    complete = load_organizer_labels(
        dataset_dir,
        SELECTION_FOLDS[0].train_start,
        FINAL_VALIDATION.val_end,
        routes=MODELED_ROUTES,
    )
    selection_count = len(SELECTION_FOLDS)
    selection_summary = {
        name: _combined_metrics(parts[:selection_count])
        for name, parts in predictions.items()
    }
    masked_selection = pd.concat(predictions["masked"][:selection_count], ignore_index=True)
    supported_selection = masked_selection[masked_selection["status"] == "ok"]
    residuals = np.abs(
        supported_selection[TARGET_COLUMN].to_numpy(dtype=float)
        - supported_selection["prediction"].to_numpy(dtype=float)
    )
    interval_absolute_error_q90 = float(np.quantile(residuals, 0.90))
    masked_validation = predictions["masked"][-1]
    supported_validation = masked_validation[masked_validation["status"] == "ok"]
    lower = np.maximum(
        supported_validation["prediction"].to_numpy(dtype=float) - interval_absolute_error_q90,
        0.0,
    )
    upper = supported_validation["prediction"].to_numpy(dtype=float) + interval_absolute_error_q90
    validation_y = supported_validation[TARGET_COLUMN].to_numpy(dtype=float)
    interval_coverage = float(np.mean((validation_y >= lower) & (validation_y <= upper)))
    return {
        "protocol": {
            "comparison": "same model and identical evaluation rows; only training rows change",
            "model": "calendar_holiday_hgbt",
            "selection_folds": [asdict(fold) for fold in SELECTION_FOLDS],
            "reused_final_validation": asdict(FINAL_VALIDATION),
            "model_scope_routes": list(MODELED_ROUTES),
            "evaluation_target_cleaned": False,
            "rounding_policy": "floor(x + 0.5); identical to submission export",
        },
        "training_mask": training_mask_summary(complete, training_mask),
        "selection_summary": selection_summary,
        "interval": {
            "method": "symmetric absolute-residual quantile calibrated on masked selection folds",
            "nominal_coverage": 0.90,
            "absolute_error_q90": interval_absolute_error_q90,
            "reused_final_validation_coverage": interval_coverage,
            "coverage_scope": "nine-route masked-training comparison; evaluation target remains uncleaned",
        },
        "adoption_decision": "requires Igor and Daniel review; no automatic adoption",
        "selected_model": "calendar_holiday_hgbt",
        "experiments": experiments,
    }


def weather_guardrail(candidate: list[pd.DataFrame], control: list[pd.DataFrame]) -> dict:
    """Paired comparisons with a route guardrail and 7-day block bootstrap."""
    deltas = []
    blocks = []
    for actual, baseline in zip(candidate, control, strict=True):
        if not actual[[*KEY_COLUMNS, TARGET_COLUMN]].equals(baseline[[*KEY_COLUMNS, TARGET_COLUMN]]):
            raise ValueError('Weather comparison requires exactly identical keys and target mask')
        a = regression_metrics(actual[TARGET_COLUMN],actual['prediction'])
        b = regression_metrics(baseline[TARGET_COLUMN],baseline['prediction'])
        deltas.append(a['wape_score'] - b['wape_score'])
        paired = pd.DataFrame({'block':(actual['horizon_day'].to_numpy()-1)//7,
            'candidate':np.abs(actual[TARGET_COLUMN].to_numpy()-actual['prediction'].to_numpy()),
            'control':np.abs(baseline[TARGET_COLUMN].to_numpy()-baseline['prediction'].to_numpy()),
            'target':actual[TARGET_COLUMN].to_numpy()})
        blocks.extend(paired.groupby('block')[['candidate','control','target']].sum().to_numpy().tolist())
    actual=pd.concat(candidate,ignore_index=True); baseline=pd.concat(control,ignore_index=True)
    route_changes={}
    for route in actual.loc[actual['status']=='ok','route'].unique():
        mask=actual['route']==route
        a=float(np.abs(actual.loc[mask,TARGET_COLUMN]-actual.loc[mask,'prediction']).mean())
        b=float(np.abs(baseline.loc[mask,TARGET_COLUMN]-baseline.loc[mask,'prediction']).mean())
        route_changes[str(route)]={'candidate_mae':a,'control_mae':b,'passed':a <= b * 1.05}
    summary=_combined_metrics(candidate); baseline_summary=_combined_metrics(control)
    positive=summary['wape_score'] > baseline_summary['wape_score']
    matrix=np.asarray(blocks)
    rng=np.random.default_rng(RANDOM_SEED)
    gains=[]
    for _ in range(500):
        sampled=matrix[rng.integers(0,len(matrix),len(matrix))].sum(axis=0)
        if sampled[2]>0:
            gains.append(max(0,1-sampled[0]/sampled[2])-max(0,1-sampled[1]/sampled[2]))
    return {'passed':bool(positive and all(delta > 0 for delta in deltas) and all(r['passed'] for r in route_changes.values())),
            'overall_gain':summary['wape_score']-baseline_summary['wape_score'],'fold_gains':deltas,'routes':route_changes,
            'uncertainty':{'method':'paired non-overlapping 7-day blocks within each fold, 500 bootstrap resamples; exploratory interval',
                           'gain_q025_q975':np.quantile(gains,[.025,.975]).tolist() if gains else None}}


def run_weather_selection(dataset_dir, config_document, factors, snapshot_manifest):
    """Select weather groups without evaluating September–October."""
    if config_document.get('schema_version') != 'weather-experiments-v1' or config_document.get('combination_policy') != 'one_combination_of_guardrail_passing_single_groups':
        raise ValueError('Unknown weather experiment protocol')
    alignment=config_document.get('alignment','legacy_timestamp_v1')
    if snapshot_manifest.get('alignment') != alignment:
        raise ValueError('Experiment and snapshot alignment disagree')
    configs=[normalize_config({**c,'alignment':alignment}) for c in config_document['experiments']]
    expected=[[],['temperature'],['precipitation'],['snow'],['wind'],['temperature','precipitation','snow','wind']]
    if [(c['id'],c['weather_groups']) for c in configs] != [(f'W0{i}',groups) for i,groups in enumerate(expected)]:
        raise ValueError('Expected the fixed W00–W05 protocol; W06 is determined only from W01–W04')
    experiments=[]; predictions={}; summary={}; checks={}
    def evaluate(config):
        key=config['id']; predictions[key]=[]
        for fold in SELECTION_FOLDS:
            record,predicted=evaluate_model(dataset_dir,fold,config['model_name'],factors=factors,experiment_config=config)
            record['decision']='pending_selection'; experiments.append(record); predictions[key].append(predicted)
        summary[key]=_combined_metrics(predictions[key])
        if key != 'W00': checks[key]=weather_guardrail(predictions[key],predictions['W00'])
    for config in configs: evaluate(config)
    groups=[c['weather_groups'][0] for c in configs[1:5] if checks[c['id']]['passed']]
    combination={'status':'not_run','reason':'Fewer than two single groups passed the predefined guardrail'}
    if len(groups)>=2:
        combined=normalize_config({'id':'W06','weather_groups':groups,'alignment':alignment})
        if set(groups)==set(configs[-1]['weather_groups']):
            combination={'status':'reused_W05','reason':'All four groups passed; this exact combination is already W05'}
        else:
            evaluate(combined); configs.append(combined)
            combination={'status':'evaluated','reason':'One combination of the single groups that passed the guardrail'}
    eligible=['W00']+[key for key,value in checks.items() if value['passed']]
    chosen=max(eligible,key=lambda key:summary[key]['wape_score'])
    chosen_config=next(c for c in configs if c['id']==chosen)
    for record in experiments:
        key=record['config']['id']
        record['decision']='selected' if key==chosen else 'control_retained' if key=='W00' else 'rejected_by_guardrail' if not checks[key]['passed'] else 'eligible_not_best'
    residuals=np.concatenate([np.abs(p.loc[p.status=='ok',TARGET_COLUMN]-p.loc[p.status=='ok','prediction']) for p in predictions[chosen]])
    return {'protocol':{'stage':'selection','selection_folds':[asdict(f) for f in SELECTION_FOLDS],
            'holdout_opened':False,'holdout_history':'September–October was used in prior work; any later assessment is reuse, not a first independent holdout',
            'target_mask':'existing organizer-label grid, unchanged','random_seed':RANDOM_SEED,'future_target_used_within_horizon':False},
            'selected_model':chosen_config['model_name'],'selected_config':chosen_config,
            'experiment_config':config_document,'snapshot':snapshot_manifest,'selection_summary':summary,'guardrails':checks,
            'combination':combination,'interval':{'absolute_error_q90':float(np.quantile(residuals,.9)),'nominal_coverage':.9,'source':'selected selection-fold residuals'},
            'experiments':experiments}, predictions


def run_frozen_holdout(dataset_dir, selection_report, factors=None):
    if selection_report.get('protocol',{}).get('stage') != 'selection':
        raise ValueError('Holdout requires a frozen selection report')
    selected=normalize_config(selection_report['selected_config'])
    experiments=[]
    for config in (normalize_config({'id':'W00','weather_groups':[]}),selected):
        if any(e['config']['id']==config['id'] for e in experiments): continue
        record,prediction=evaluate_model(dataset_dir,FINAL_HOLDOUT,config['model_name'],factors=factors,experiment_config=config)
        record['decision']='reused_holdout_after_frozen_selection_no_retuning'
        q90=selection_report['interval']['absolute_error_q90']
        supported=prediction[prediction.status=='ok']
        record['interval_coverage']=float((np.abs(supported[TARGET_COLUMN]-supported['prediction']) <= q90).mean())
        rounded=prediction.copy(); rounded['prediction']=np.floor(rounded['prediction']+.5)
        record['metrics_after_submission_rounding']=slice_metrics(rounded)
        experiments.append(record)
    return {**selection_report,'protocol':{**selection_report['protocol'],'stage':'holdout','holdout_opened':True,'holdout_reused':True},'experiments':experiments}
