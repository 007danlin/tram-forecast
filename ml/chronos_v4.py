"""Full preregistered Chronos-2 N1/N2 evaluation for score-v4."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
import pandas as pd

from ml.chronos_smoke import CHECKPOINT_REVISION, MODELED_ROUTES, calendar_frame, hourly_from_daily, load_labels, sha256_file


TARGETS = [f"h{hour:02d}" for hour in range(24)]


def _metric(frame: pd.DataFrame) -> dict:
    prediction = np.floor(np.maximum(frame.prediction.to_numpy(dtype=float), 0.0) + 0.5)
    y = frame.boardings.to_numpy(dtype=float)
    sae, total = float(np.abs(y - prediction).sum()), float(y.sum())
    return {
        "score": max(0.0, 1.0 - sae / total), "sae": sae, "sum_y": total,
        "signed_bias": float((prediction - y).sum()), "rows": len(frame),
    }


def _calendar_join(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    calendar = calendar_frame(result.timestamp)
    for column in calendar:
        result[column] = calendar[column].to_numpy()
    return result


def _n1_frames(labels: pd.DataFrame, cutoff: pd.Timestamp, start: pd.Timestamp, end: pd.Timestamp):
    context = labels[labels.date.le(cutoff)].pivot(index=["route", "date"], columns="hour", values="boardings").reset_index()
    context = context.rename(columns={"route": "item_id", "date": "timestamp", **{hour: f"h{hour:02d}" for hour in range(24)}})
    context = _calendar_join(context)
    future = pd.MultiIndex.from_product([MODELED_ROUTES, pd.date_range(start, end)], names=["item_id", "timestamp"]).to_frame(index=False)
    future = _calendar_join(future)
    return context, future


def _n2_frames(labels: pd.DataFrame, cutoff: pd.Timestamp, start: pd.Timestamp, end: pd.Timestamp):
    daily = labels.groupby(["route", "date"], as_index=False).boardings.sum()
    context = daily[daily.date.le(cutoff)].rename(columns={"route": "item_id", "date": "timestamp", "boardings": "target"})
    context = _calendar_join(context)
    future = pd.MultiIndex.from_product([MODELED_ROUTES, pd.date_range(start, end)], names=["item_id", "timestamp"]).to_frame(index=False)
    future = _calendar_join(future)
    return context, future


def _forecast_n1(pipeline, labels: pd.DataFrame, fold: dict) -> pd.DataFrame:
    cutoff, start, end = map(pd.Timestamp, (fold["train_end"], fold["start"], fold["end"]))
    context, future = _n1_frames(labels, cutoff, start, end)
    prediction = pipeline.predict_df(
        context, future_df=future, id_column="item_id", timestamp_column="timestamp",
        target=TARGETS, prediction_length=61, quantile_levels=[0.1, 0.5, 0.9],
        batch_size=64, freq="D", cross_learning=True,
    )
    required = {"item_id", "timestamp", "target_name", "predictions"}
    if not required.issubset(prediction.columns):
        raise ValueError(f"Unexpected Chronos N1 columns: {prediction.columns.tolist()}")
    prediction["hour"] = prediction.target_name.str.extract(r"^h(\d{2})$", expand=False).astype(int)
    result = prediction.rename(columns={"item_id": "route", "timestamp": "date", "predictions": "prediction"})
    actual = labels[labels.date.between(start, end)][["route", "date", "hour", "boardings"]]
    result = actual.merge(result[["route", "date", "hour", "prediction"]], on=["route", "date", "hour"], validate="one_to_one")
    return result


def _forecast_n2(pipeline, labels: pd.DataFrame, b2: pd.DataFrame, fold: dict) -> pd.DataFrame:
    cutoff, start, end = map(pd.Timestamp, (fold["train_end"], fold["start"], fold["end"]))
    context, future = _n2_frames(labels, cutoff, start, end)
    prediction = pipeline.predict_df(
        context, future_df=future, id_column="item_id", timestamp_column="timestamp",
        target="target", prediction_length=61, quantile_levels=[0.1, 0.5, 0.9],
        batch_size=16, freq="D", cross_learning=True,
    )
    daily = prediction[["item_id", "timestamp", "predictions"]].rename(
        columns={"item_id": "route", "timestamp": "date", "predictions": "daily_prediction"}
    )
    daily.daily_prediction = daily.daily_prediction.clip(lower=0.0)
    shape = b2[b2.fold.eq(fold["id"])].copy()
    return hourly_from_daily(daily, shape)[["route", "date", "hour", "boardings", "prediction"]]


def run(dataset_dir: str, config_path: str, b2_oof_path: str, output_dir: str, checkpoint: str, revision: str = CHECKPOINT_REVISION) -> dict:
    from chronos import BaseChronosPipeline
    from huggingface_hub import model_info
    import torch

    output = Path(output_dir)
    if output.exists():
        raise ValueError("Chronos v4 output exists")
    output.mkdir(parents=True)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    folds = config["folds"]
    labels = load_labels(Path(dataset_dir), "2025-01-01", "2025-09-30")
    b2 = pd.read_csv(b2_oof_path, parse_dates=["date"], float_precision="round_trip")
    info = model_info(checkpoint, revision=revision)
    load_started = time.monotonic()
    pipeline = BaseChronosPipeline.from_pretrained(checkpoint, revision=info.sha, device_map="cpu", torch_dtype=torch.float32)
    load_seconds = time.monotonic() - load_started
    all_results, timings = {}, {}
    for experiment_id, callback in (("N1", _forecast_n1), ("N2", _forecast_n2)):
        parts, per_fold = [], {}
        for fold in folds:
            started = time.monotonic()
            frame = callback(pipeline, labels, fold) if experiment_id == "N1" else callback(pipeline, labels, b2, fold)
            frame["fold"] = fold["id"]
            frame["horizon_day"] = (frame.date - pd.Timestamp(fold["start"])).dt.days + 1
            if len(frame) != 9 * 61 * 24 or not np.isfinite(frame.prediction).all():
                raise ValueError(f"Invalid {experiment_id}/{fold['id']} output")
            frame.prediction = frame.prediction.clip(lower=0.0)
            seconds = time.monotonic() - started
            per_fold[fold["id"]] = {**_metric(frame), "seconds": seconds}
            parts.append(frame)
            print(json.dumps({"event": "chronos_fold", "id": experiment_id, "fold": fold["id"], "seconds": seconds, "score": per_fold[fold["id"]]["score"]}), flush=True)
        combined = pd.concat(parts, ignore_index=True)
        combined.to_csv(output / f"{experiment_id}-oof.csv", index=False, encoding="utf-8", lineterminator="\n")
        all_results[experiment_id] = {"combined": _metric(combined), "folds": per_fold, "oof_sha256": sha256_file(output / f"{experiment_id}-oof.csv")}
        timings[experiment_id] = sum(value["seconds"] for value in per_fold.values())
    license_name = getattr(getattr(info, "card_data", None), "license", None)
    result = {
        "schema": "score-v4-chronos-result", "checkpoint": checkpoint,
        "checkpoint_revision": info.sha, "license": license_name,
        "source": f"https://huggingface.co/{checkpoint}", "hosted_inference_api": False,
        "point_output": "predictions; Chronos-2 source documents its point output as the median quantile",
        "representations": {
            "N1": "nine route groups with 24 daily route-hour target columns; cross_learning=True",
            "N2": "nine daily route totals distributed with same-origin B2 hourly shape",
        },
        "calendar_future_covariates": ["dow", "is_day_off", "is_public_holiday", "day_of_year_sin", "day_of_year_cos"],
        "load_seconds": load_seconds, "inference_seconds": timings,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "results": all_results,
        "versions": {name: importlib.metadata.version(name) for name in ("chronos-forecasting", "torch", "transformers", "huggingface-hub", "numpy", "pandas")},
        "python": sys.version, "platform": platform.platform(),
    }
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--config", default="ml/experiments/score-v4.json")
    parser.add_argument("--b2-oof", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoint", default="amazon/chronos-2")
    parser.add_argument("--revision", default=CHECKPOINT_REVISION)
    args = parser.parse_args()
    result = run(args.dataset_dir, args.config, args.b2_oof, args.output, args.checkpoint, args.revision)
    print(json.dumps({"output": args.output, "revision": result["checkpoint_revision"], "results": result["results"]}))


if __name__ == "__main__":
    main()
