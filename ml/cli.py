"""Command-line entry points for evaluation, training, and batch inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ml.artifact import create_artifact, load_artifact, predict_artifact, submission_preflight, write_submission
from ml.data import build_target_from_raw, load_organizer_labels
from ml.evaluation import experiment_log_frame, run_full_evaluation
from ml.factors import WEATHER_SOURCE_URL, load_weather_factors, normalize_open_meteo_snapshot
from ml.settings import FINAL_TRAIN_END, FINAL_TRAIN_START, FORECAST_END, FORECAST_START, KEY_COLUMNS, TARGET_COLUMN


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
    factors = load_weather_factors(args.weather_factors) if args.weather_factors else None
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
    destination = create_artifact(
        args.dataset_dir,
        args.artifact_dir,
        model_name=report["selected_model"],
        interval_absolute_error_q90=report["interval"]["absolute_error_q90"],
        factor_path=args.weather_factors,
    )
    print(json.dumps({"artifact_dir": str(destination), "model": report["selected_model"]}, ensure_ascii=False))
    return 0


def command_forecast(args: argparse.Namespace) -> int:
    prediction = predict_artifact(args.artifact_dir, args.start, args.end)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    prediction.to_csv(destination, sep=";", index=False, encoding="utf-8", lineterminator="\n")
    print(json.dumps({"output": str(destination), "rows": len(prediction)}, ensure_ascii=False))
    return 0


def command_submission(args: argparse.Namespace) -> int:
    prediction = predict_artifact(args.artifact_dir, FORECAST_START, FORECAST_END)
    output = write_submission(prediction, args.template, args.output)
    preflight = submission_preflight(output, args.template)
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
            {"output": str(output), "rows": len(prediction), "preflight": str(preflight_path), "passed": preflight["passed"]},
            ensure_ascii=False,
        )
    )
    return 0 if preflight["passed"] else 3


def command_prepare_weather(args: argparse.Namespace) -> int:
    output, manifest = normalize_open_meteo_snapshot(
        args.snapshot,
        args.output,
        args.manifest,
        source_url=args.source_url,
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

    verify = subparsers.add_parser("verify-target", help="Rebuild labels from raw CSV in chunks")
    verify.add_argument("--dataset-dir", required=True)
    verify.add_argument("--chunksize", type=int, default=500_000)
    verify.set_defaults(func=command_verify_target)

    backtest = subparsers.add_parser("backtest", help="Select a model, then evaluate the final holdout once")
    backtest.add_argument("--dataset-dir", required=True)
    backtest.add_argument("--output", required=True)
    backtest.add_argument("--experiment-log", default="ml/reports/experiment-log.csv")
    backtest.add_argument("--weather-factors")
    backtest.set_defaults(func=command_backtest)

    train = subparsers.add_parser("train", help="Fit the selected model on January-October")
    train.add_argument("--dataset-dir", required=True)
    train.add_argument("--evaluation-report", required=True)
    train.add_argument("--artifact-dir", required=True)
    train.add_argument("--weather-factors")
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
    submission.set_defaults(func=command_submission)

    weather = subparsers.add_parser("prepare-weather", help="Validate and normalize an Open-Meteo JSON snapshot")
    weather.add_argument("--snapshot", required=True)
    weather.add_argument("--output", required=True)
    weather.add_argument("--manifest", required=True)
    weather.add_argument("--source-url", default=WEATHER_SOURCE_URL)
    weather.set_defaults(func=command_prepare_weather)

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
