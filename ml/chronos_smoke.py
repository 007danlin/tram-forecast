"""One bounded Chronos-2 zero-shot smoke for score-v4.

The script uses nine daily route totals and known calendar covariates.  It
scores the resulting hourly forecast after distributing daily totals with the
origin-safe incumbent B2 shape.  No data is sent to a hosted inference API.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
import pandas as pd


MODELED_ROUTES = (1, 7, 11, 12, 17, 25, 26, 28, 50)
CHECKPOINT_REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calendar_frame(dates: pd.Series | pd.DatetimeIndex) -> pd.DataFrame:
    values = pd.DatetimeIndex(pd.to_datetime(dates)).normalize()
    holidays = set(pd.date_range("2025-01-01", "2025-01-08")) | {
        pd.Timestamp("2025-02-23"), pd.Timestamp("2025-03-08"), pd.Timestamp("2025-05-01"),
        pd.Timestamp("2025-05-09"), pd.Timestamp("2025-06-12"), pd.Timestamp("2025-11-04"),
    }
    transferred = {
        pd.Timestamp("2025-05-02"), pd.Timestamp("2025-05-08"), pd.Timestamp("2025-06-13"),
        pd.Timestamp("2025-11-03"), pd.Timestamp("2025-12-31"),
    }
    working_weekends = {pd.Timestamp("2025-11-01")}
    day_off = ((values.dayofweek >= 5) & ~values.isin(working_weekends)) | values.isin(holidays | transferred)
    day = values.dayofyear.to_numpy(dtype=float)
    return pd.DataFrame({
        "dow": values.dayofweek.astype(str),
        "is_day_off": day_off.astype(float),
        "is_public_holiday": values.isin(holidays).astype(float),
        "day_of_year_sin": np.sin(2.0 * np.pi * day / 365.25),
        "day_of_year_cos": np.cos(2.0 * np.pi * day / 365.25),
    })


def load_labels(dataset: Path, start: str, end: str) -> pd.DataFrame:
    parts = [
        pd.read_csv(dataset / "labels" / name, sep=";", dtype={"route": int, "hour": int, "boardings": int})
        for name in ("labels_day_train.csv", "labels_day_test.csv")
    ]
    labels = pd.concat(parts, ignore_index=True)
    labels["date"] = pd.to_datetime(labels.date, format="%Y-%m-%d")
    labels = labels[labels.route.isin(MODELED_ROUTES) & labels.date.between(start, end)]
    grid = pd.MultiIndex.from_product(
        [MODELED_ROUTES, pd.date_range(start, end), range(24)], names=["route", "date", "hour"]
    ).to_frame(index=False)
    result = grid.merge(labels, on=["route", "date", "hour"], how="left", validate="one_to_one")
    result["boardings"] = result.boardings.fillna(0).astype(int)
    return result


def hourly_from_daily(daily_prediction: pd.DataFrame, b2_oof: pd.DataFrame) -> pd.DataFrame:
    shape = b2_oof.copy()
    totals = shape.groupby(["route", "date"]).prediction.transform("sum").to_numpy(dtype=float)
    fallback = np.full(len(shape), 1.0 / 24.0)
    shape["share"] = np.divide(shape.prediction.to_numpy(dtype=float), totals, out=fallback, where=totals > 0)
    result = shape.merge(daily_prediction, on=["route", "date"], validate="many_to_one")
    result["prediction"] = np.maximum(result.daily_prediction.to_numpy(dtype=float) * result.share.to_numpy(dtype=float), 0.0)
    return result


def run(dataset_dir: str, b2_oof_path: str, output_dir: str, checkpoint: str, revision: str = CHECKPOINT_REVISION) -> dict:
    from chronos import BaseChronosPipeline
    from huggingface_hub import model_info
    import torch

    dataset, output = Path(dataset_dir), Path(output_dir)
    if output.exists():
        raise ValueError("Chronos smoke output exists")
    output.mkdir(parents=True)
    cutoff, start, end = pd.Timestamp("2025-07-31"), pd.Timestamp("2025-08-01"), pd.Timestamp("2025-09-30")
    labels = load_labels(dataset, "2025-01-01", "2025-09-30")
    daily = labels.groupby(["route", "date"], as_index=False).boardings.sum()
    context = daily[daily.date.le(cutoff)].rename(columns={"route": "item_id", "date": "timestamp", "boardings": "target"})
    context_calendar = calendar_frame(context.timestamp)
    for column in context_calendar:
        context[column] = context_calendar[column].to_numpy()
    future = pd.MultiIndex.from_product([MODELED_ROUTES, pd.date_range(start, end)], names=["item_id", "timestamp"]).to_frame(index=False)
    future_calendar = calendar_frame(future.timestamp)
    for column in future_calendar:
        future[column] = future_calendar[column].to_numpy()

    info = model_info(checkpoint, revision=revision)
    started_load = time.monotonic()
    pipeline = BaseChronosPipeline.from_pretrained(
        checkpoint, revision=info.sha, device_map="cpu", torch_dtype=torch.float32,
    )
    load_seconds = time.monotonic() - started_load
    started = time.monotonic()
    forecast = pipeline.predict_df(
        context, future_df=future, id_column="item_id", timestamp_column="timestamp",
        target="target", prediction_length=61, quantile_levels=[0.1, 0.5, 0.9],
        batch_size=16, freq="D",
    )
    inference_seconds = time.monotonic() - started
    if len(forecast) != 9 * 61 or not np.isfinite(forecast.predictions).all():
        raise ValueError("Chronos smoke returned incomplete or non-finite daily forecasts")
    daily_prediction = forecast[["item_id", "timestamp", "predictions"]].rename(
        columns={"item_id": "route", "timestamp": "date", "predictions": "daily_prediction"}
    )
    daily_prediction["daily_prediction"] = daily_prediction.daily_prediction.clip(lower=0.0)
    b2 = pd.read_csv(b2_oof_path, parse_dates=["date"], float_precision="round_trip")
    b2 = b2[b2.fold.eq("S4")].copy()
    hourly = hourly_from_daily(daily_prediction, b2)
    rounded = np.floor(hourly.prediction.to_numpy(dtype=float) + 0.5)
    actual = hourly.boardings.to_numpy(dtype=float)
    sae = float(np.abs(actual - rounded).sum())
    sum_y = float(actual.sum())
    score = max(0.0, 1.0 - sae / sum_y)
    bias = float((rounded - actual).sum())
    daily_prediction.to_csv(output / "daily-predictions.csv", index=False, encoding="utf-8", lineterminator="\n")
    hourly[["route", "date", "hour", "boardings", "prediction", "fold", "horizon_day"]].to_csv(
        output / "hourly-oof.csv", index=False, encoding="utf-8", lineterminator="\n"
    )
    license_name = None
    if getattr(info, "card_data", None) is not None:
        license_name = getattr(info.card_data, "license", None)
    result = {
        "schema": "score-v4-chronos-smoke",
        "representation": "N2: nine daily route totals distributed with same-origin B2 hourly shape",
        "checkpoint": checkpoint,
        "checkpoint_revision": info.sha,
        "license": license_name,
        "source": f"https://huggingface.co/{checkpoint}",
        "hosted_inference_api": False,
        "cutoff": str(cutoff.date()), "start": str(start.date()), "end": str(end.date()),
        "series": 9, "prediction_length": 61, "calendar_future_covariates": list(future_calendar.columns),
        "load_seconds": load_seconds, "inference_seconds": inference_seconds,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "daily_rows": len(daily_prediction), "hourly_rows": len(hourly),
        "finite": True, "nonnegative_after_single_clip": True,
        "rounded_score": score, "sae": sae, "sum_y": sum_y, "signed_bias": bias,
        "daily_sha256": sha256_file(output / "daily-predictions.csv"),
        "hourly_sha256": sha256_file(output / "hourly-oof.csv"),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("chronos-forecasting", "torch", "transformers", "huggingface-hub", "numpy", "pandas")
        },
        "python": sys.version, "platform": platform.platform(),
    }
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--b2-oof", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoint", default="amazon/chronos-2")
    parser.add_argument("--revision", default=CHECKPOINT_REVISION)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset_dir, args.b2_oof, args.output, args.checkpoint, args.revision), ensure_ascii=False))


if __name__ == "__main__":
    main()
