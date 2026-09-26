"""Command-line entry points for evaluation, training, and batch inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ml.artifact import create_artifact, load_artifact, predict_artifact, submission_preflight, write_submission
from ml.data import build_target_from_raw, load_organizer_labels
from ml.evaluation import (
    experiment_log_frame,
    run_frozen_holdout,
    run_full_evaluation,
    run_training_mask_comparison,
    run_weather_selection,
)
from ml.factors import sha256_file, ALIGNMENTS, WEATHER_SOURCE_URL, load_weather_factors, normalize_open_meteo_snapshot
from ml.weather import fetch_weather
from ml.qa import history_drop_candidates, load_training_mask
from ml.settings import (
    FINAL_TRAIN_END,
    FINAL_TRAIN_START,
    FORECAST_END,
    FORECAST_START,
    KEY_COLUMNS,
    MODELED_ROUTES,
    TARGET_COLUMN,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def command_verify_target(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset_dir)
    rebuilt = build_target_from_raw(
        [dataset / "train.csv", dataset / "test.csv"],
        FINAL_TRAIN_START,
        FINAL_TRAIN_END,
        chunksize=args.chunksize,
    )
    labels = load_organizer_labels(dataset, FINAL_TRAIN_START, FINAL_TRAIN_END)
    compared = rebuilt.merge(
        labels[[*KEY_COLUMNS, TARGET_COLUMN]],
        on=list(KEY_COLUMNS),
        suffixes=("_raw", "_labels"),
        validate="one_to_one",
    )
    different = compared[compared[f"{TARGET_COLUMN}_raw"] != compared[f"{TARGET_COLUMN}_labels"]]
    result = {
        "rows": len(compared),
        "different_rows": len(different),
        "raw_total": int(compared[f"{TARGET_COLUMN}_raw"].sum()),
        "labels_total": int(compared[f"{TARGET_COLUMN}_labels"].sum()),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if different.empty else 2


def command_backtest(args: argparse.Namespace) -> int:
    destination, log_destination = Path(args.output), Path(args.experiment_log)
    if destination.exists() or log_destination.exists():
        raise ValueError("Evaluation report/log already exists; use new local paths to preserve experiment history")
    factors = load_weather_factors(args.weather_factors) if args.weather_factors else None
    snapshot = None
    if args.stage != "full":
        if args.weather_factors:
            manifest_path = Path(args.weather_manifest) if args.weather_manifest else Path(args.weather_factors).with_name("manifest.json")
            snapshot = json.loads(manifest_path.read_text())
            if snapshot["normalized"]["sha256"] != sha256_file(args.weather_factors):
                raise ValueError("Weather snapshot checksum mismatch")
        if args.stage == "selection":
            if not args.experiment_config or factors is None or snapshot is None:
                raise ValueError("Selection requires --experiment-config and a verified weather snapshot")
            report, _ = run_weather_selection(args.dataset_dir, json.loads(Path(args.experiment_config).read_text()), factors, snapshot)
        else:
            if not args.selection_report:
                raise ValueError("Holdout requires --selection-report")
            frozen = json.loads(Path(args.selection_report).read_text())
            if frozen["selected_config"]["weather_groups"] and snapshot != frozen["snapshot"]:
                raise ValueError("Holdout snapshot differs from frozen selection")
            report = run_frozen_holdout(args.dataset_dir, frozen, factors)
    else:
        if args.experiment_config:
            raise ValueError("Weather experiments require --stage selection, then explicit frozen holdout")
        report, _ = run_full_evaluation(args.dataset_dir, factors=factors)
    destination = Path(args.output)
    _write_json(destination, report)
    log_destination = Path(args.experiment_log)
    log_destination.parent.mkdir(parents=True, exist_ok=True)
    experiment_log_frame(report).to_csv(log_destination, index=False, encoding="utf-8", lineterminator="\n")
    print(
        json.dumps(
            {
                "report": str(destination),
                "experiment_log": str(log_destination),
                "selected_model": report["selected_model"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_train(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.evaluation_report).read_text(encoding="utf-8"))
    if args.training_mask:
        mask = load_training_mask(args.training_mask)
        report_mask = report.get("training_mask") or {}
        if report.get("adoption_decision") != "adopted":
            raise ValueError(
                "Masked training requires a reviewed comparison report with adoption_decision='adopted'"
            )
        if report_mask.get("mask_id") != mask["mask_id"] or report_mask.get("mask_sha256") != mask["sha256"]:
            raise ValueError("Training mask differs from the reviewed comparison report")
    destination = create_artifact(
        args.dataset_dir,
        args.artifact_dir,
        model_name=report["selected_model"],
        interval_absolute_error_q90=report["interval"]["absolute_error_q90"],
        factor_path=args.weather_factors,
        experiment_config=report.get("selected_config"),
        snapshot_manifest=report.get("snapshot"),
        training_mask_path=args.training_mask,
    )
    print(json.dumps({"artifact_dir": str(destination), "model": report["selected_model"]}, ensure_ascii=False))
    return 0


def command_improve_score(args: argparse.Namespace) -> int:
    from ml.score_improvement import run_study
    result = run_study(args.dataset_dir, args.config, args.baseline_artifact,
                       args.baseline_submission, args.output_dir, args.resume)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_score_v3(args: argparse.Namespace) -> int:
    from ml.score_v3_study import run_study

    result = run_study(
        args.dataset_dir,
        args.config,
        args.output_dir,
        resume=args.resume,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_forecast(args: argparse.Namespace) -> int:
    if Path(args.output).exists():
        raise ValueError("Forecast exists; choose a new output")
    prediction = predict_artifact(args.artifact_dir, args.start, args.end)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    prediction.to_csv(destination, sep=";", index=False, encoding="utf-8", lineterminator="\n")
    print(json.dumps({"output": str(destination), "rows": len(prediction)}, ensure_ascii=False))
    return 0


def command_submission(args: argparse.Namespace) -> int:
    preflight_path = Path(args.preflight_output) if args.preflight_output else Path(args.output).with_suffix(".preflight.json")
    if Path(args.output).exists() or preflight_path.exists():
        raise ValueError("Submission/preflight exists; choose new outputs")
    prediction = predict_artifact(args.artifact_dir, FORECAST_START, FORECAST_END)
    output = write_submission(prediction, args.template, args.output, scope=args.scope)
    preflight = submission_preflight(output, args.template, scope=args.scope)
    _, metadata = load_artifact(args.artifact_dir)
    preflight["artifact"] = {
        "schema_version": metadata["schema_version"],
        "model_name": metadata["model_name"],
        "information_mode": metadata.get("information_mode", "operational"),
        "random_seed": metadata.get("random_seed"),
    }
    preflight_path = Path(args.preflight_output) if args.preflight_output else output.with_suffix(".preflight.json")
    _write_json(preflight_path, preflight)
    print(
        json.dumps(
            {
                "output": str(output),
                "rows": preflight["checks"]["expected_row_count"],
                "scope": args.scope,
                "preflight": str(preflight_path),
                "passed": preflight["passed"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if preflight["passed"] else 3


def command_compare_training_mask(args: argparse.Namespace) -> int:
    destination, log_destination = Path(args.output), Path(args.experiment_log)
    if destination.exists() or log_destination.exists():
        raise ValueError("Mask comparison report/log already exists; use new paths")
    mask = load_training_mask(args.training_mask)
    report = run_training_mask_comparison(args.dataset_dir, mask)
    _write_json(destination, report)
    log_destination.parent.mkdir(parents=True, exist_ok=True)
    experiment_log_frame(report).to_csv(
        log_destination,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
    )
    print(
        json.dumps(
            {
                "report": str(destination),
                "experiment_log": str(log_destination),
                "mask_id": mask["mask_id"],
                "adoption_decision": report["adoption_decision"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_audit_history(args: argparse.Namespace) -> int:
    target = load_organizer_labels(
        args.dataset_dir,
        FINAL_TRAIN_START,
        FINAL_TRAIN_END,
        routes=MODELED_ROUTES,
    )
    candidates = history_drop_candidates(
        target,
        lookback_weeks=args.lookback_weeks,
        ratio_threshold=args.ratio_threshold,
        minimum_baseline=args.minimum_baseline,
    )
    payload = {
        "model_scope_routes": list(MODELED_ROUTES),
        "method": (
            "daily target divided by the median of the previous comparable weekdays; "
            "candidate detection only, no causal label and no automatic recovery"
        ),
        "parameters": {
            "lookback_weeks": args.lookback_weeks,
            "ratio_threshold": args.ratio_threshold,
            "minimum_baseline": args.minimum_baseline,
        },
        "candidate_count": len(candidates),
        "candidates": candidates.to_dict(orient="records"),
    }
    _write_json(Path(args.output), payload)
    print(json.dumps({"output": args.output, "candidate_count": len(candidates)}, ensure_ascii=False))
    return 0


def command_prepare_weather(args: argparse.Namespace) -> int:
    output, manifest = normalize_open_meteo_snapshot(
        args.snapshot,
        args.output,
        args.manifest,
        source_url=args.source_url,
        start=args.start, end=args.end, receipt_path=args.receipt, alignment=args.alignment,
    )
    factors = load_weather_factors(output)
    print(
        json.dumps(
            {
                "output": str(output),
                "manifest": str(manifest),
                "rows": len(factors),
                "start": str(factors["timestamp"].min()),
                "end": str(factors["timestamp"].max()),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_fetch_weather(args: argparse.Namespace) -> int:
    print(json.dumps(fetch_weather(args.start, args.end, args.output_dir, offline=args.offline, alignment=args.alignment)))
    return 0


def command_month(args: argparse.Namespace) -> int:
    prediction = predict_artifact(args.artifact_dir, args.start, args.end)
    daily = prediction.groupby(["route", "date"], as_index=False).agg(
        prediction=("prediction", "sum"),
        reference_value=("reference_value", "sum"),
        peak_hour=("prediction", lambda values: int(prediction.loc[values.index, "hour"].iloc[values.to_numpy().argmax()])),
        peak_value=("prediction", "max"),
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(destination, sep=";", index=False, encoding="utf-8", lineterminator="\n")
    print(json.dumps({"output": str(destination), "rows": len(daily)}, ensure_ascii=False))
    return 0


def command_year_scenario(args: argparse.Namespace) -> int:
    payload = {
        "mode": "qualitative",
        "value": None,
        "supported": False,
        "reason": "Only ten months of history are available; annual seasonality and calibrated yearly intervals cannot be validated.",
        "scenarios": [
            {"name": "recent_level", "assumption": "Demand remains near the latest validated route-hour profile."},
            {"name": "lower_service", "assumption": "Known service reductions may lower affected route periods; no magnitude is asserted."},
            {"name": "higher_demand", "assumption": "Demand may exceed the recent profile; no unsupported numeric uplift is asserted."},
        ],
    }
    _write_json(Path(args.output), payload)
    print(json.dumps({"output": args.output, "mode": "qualitative"}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TramFlow reproducible ML batch pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    improve = subparsers.add_parser("improve-score", help="Run the bounded score-improvement-v2 study")
    improve.add_argument("--dataset-dir", required=True)
    improve.add_argument("--config", required=True)
    improve.add_argument("--baseline-artifact", required=True)
    improve.add_argument("--baseline-submission", required=True)
    improve.add_argument("--output-dir", required=True)
    improve.add_argument("--resume", action="store_true")
    improve.set_defaults(func=command_improve_score)

    score_v3 = subparsers.add_parser("score-v3", help="Run the bounded origin-safe score-v3 study")
    score_v3.add_argument("--dataset-dir", required=True)
    score_v3.add_argument("--config", default="ml/experiments/score-v3.json")
    score_v3.add_argument("--output-dir", required=True)
    score_v3.add_argument("--resume", action="store_true")
    score_v3.set_defaults(func=command_score_v3)

    verify = subparsers.add_parser("verify-target", help="Rebuild labels from raw CSV in chunks")
    verify.add_argument("--dataset-dir", required=True)
    verify.add_argument("--chunksize", type=int, default=500_000)
    verify.set_defaults(func=command_verify_target)

    backtest = subparsers.add_parser("backtest", help="Select on early folds, then evaluate the reused 61-day validation")
    backtest.add_argument("--dataset-dir", required=True)
    backtest.add_argument("--output", required=True)
    backtest.add_argument("--experiment-log", default="artifacts/experiments/experiment-log.csv")
    backtest.add_argument("--weather-factors")
    backtest.add_argument("--weather-manifest")
    backtest.add_argument("--stage", choices=("full", "selection", "holdout"), default="full")
    backtest.add_argument("--experiment-config")
    backtest.add_argument("--selection-report")
    backtest.set_defaults(func=command_backtest)

    train = subparsers.add_parser("train", help="Fit the selected model on January-October")
    train.add_argument("--dataset-dir", required=True)
    train.add_argument("--evaluation-report", required=True)
    train.add_argument("--artifact-dir", required=True)
    train.add_argument("--weather-factors")
    train.add_argument("--training-mask")
    train.set_defaults(func=command_train)

    forecast = subparsers.add_parser("forecast", help="Write internal non-rounded hourly forecast")
    forecast.add_argument("--artifact-dir", required=True)
    forecast.add_argument("--start", required=True)
    forecast.add_argument("--end", required=True)
    forecast.add_argument("--output", required=True)
    forecast.set_defaults(func=command_forecast)

    submission = subparsers.add_parser("submission", help="Write strict organizer submission")
    submission.add_argument("--artifact-dir", required=True)
    submission.add_argument("--template", required=True)
    submission.add_argument("--output", required=True)
    submission.add_argument("--preflight-output")
    submission.add_argument("--scope", choices=("sample", "modeled_routes"), default="sample")
    submission.set_defaults(func=command_submission)

    compare_mask = subparsers.add_parser(
        "compare-training-mask",
        help="Compare the frozen calendar model before/after a verified hour mask",
    )
    compare_mask.add_argument("--dataset-dir", required=True)
    compare_mask.add_argument("--training-mask", required=True)
    compare_mask.add_argument("--output", required=True)
    compare_mask.add_argument("--experiment-log", required=True)
    compare_mask.set_defaults(func=command_compare_training_mask)

    history = subparsers.add_parser(
        "audit-history",
        help="Report large daily drops without imputing or assigning a cause",
    )
    history.add_argument("--dataset-dir", required=True)
    history.add_argument("--output", required=True)
    history.add_argument("--lookback-weeks", type=int, default=4)
    history.add_argument("--ratio-threshold", type=float, default=0.10)
    history.add_argument("--minimum-baseline", type=float, default=100.0)
    history.set_defaults(func=command_audit_history)

    weather = subparsers.add_parser("prepare-weather", help="Validate and normalize an Open-Meteo JSON snapshot")
    weather.add_argument("--snapshot", required=True)
    weather.add_argument("--output", required=True)
    weather.add_argument("--manifest", required=True)
    weather.add_argument("--source-url", default=WEATHER_SOURCE_URL)
    weather.add_argument("--start")
    weather.add_argument("--end")
    weather.add_argument("--receipt")
    weather.add_argument("--alignment", choices=ALIGNMENTS, default=ALIGNMENTS[0])
    weather.set_defaults(func=command_prepare_weather)

    fetch = subparsers.add_parser("fetch-weather", help="Acquire and validate an immutable ERA5 snapshot, or verify it offline")
    fetch.add_argument("--start", required=True)
    fetch.add_argument("--end", required=True)
    fetch.add_argument("--output-dir", required=True)
    fetch.add_argument("--offline", action="store_true")
    fetch.add_argument("--alignment", choices=ALIGNMENTS, default=ALIGNMENTS[0])
    fetch.set_defaults(func=command_fetch_weather)

    month = subparsers.add_parser("month", help="Aggregate an hourly artifact forecast to daily values and peaks")
    month.add_argument("--artifact-dir", required=True)
    month.add_argument("--start", required=True)
    month.add_argument("--end", required=True)
    month.add_argument("--output", required=True)
    month.set_defaults(func=command_month)

    year = subparsers.add_parser("year-scenario", help="Emit the documented qualitative yearly mode")
    year.add_argument("--output", required=True)
    year.set_defaults(func=command_year_scenario)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
