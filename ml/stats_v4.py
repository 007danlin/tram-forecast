"""C1/C2 damped weekly AutoETS evaluation for score-v4."""

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

from ml.chronos_smoke import MODELED_ROUTES, hourly_from_daily, load_labels, sha256_file


SPECIAL_DATES = set(pd.date_range("2025-01-01", "2025-01-08")) | {
    pd.Timestamp("2025-02-23"), pd.Timestamp("2025-03-08"), pd.Timestamp("2025-05-01"),
    pd.Timestamp("2025-05-02"), pd.Timestamp("2025-05-08"), pd.Timestamp("2025-05-09"),
    pd.Timestamp("2025-06-12"), pd.Timestamp("2025-06-13"), pd.Timestamp("2025-11-01"),
    pd.Timestamp("2025-11-03"), pd.Timestamp("2025-11-04"), pd.Timestamp("2025-12-31"),
}


def _metric(frame: pd.DataFrame) -> dict:
    prediction = np.floor(np.maximum(frame.prediction.to_numpy(dtype=float), 0.0) + 0.5)
    y = frame.boardings.to_numpy(dtype=float)
    sae, total = float(np.abs(y - prediction).sum()), float(y.sum())
    return {"score": max(0.0, 1.0 - sae / total), "sae": sae, "sum_y": total,
            "signed_bias": float((prediction - y).sum()), "rows": len(frame)}


def _forecast(data: pd.DataFrame, horizon: int) -> pd.DataFrame:
    from statsforecast import StatsForecast
    from statsforecast.models import AutoETS
    model = AutoETS(season_length=7, model="ZZZ", damped=True, alias="AutoETS")
    engine = StatsForecast(models=[model], freq="D", n_jobs=4)
    result = engine.forecast(df=data, h=horizon)
    if "AutoETS" not in result.columns:
        raise ValueError(f"Unexpected StatsForecast columns: {result.columns.tolist()}")
    return result.rename(columns={"AutoETS": "prediction"})


def _c1_input(labels: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    result = labels[labels.date.le(cutoff)][["route", "date", "hour", "boardings"]].copy()
    result["unique_id"] = result.route.astype(str) + "_" + result.hour.astype(str).str.zfill(2)
    return result.rename(columns={"date": "ds", "boardings": "y"})[["unique_id", "ds", "y"]]


def _c2_input(labels: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    result = labels[labels.date.le(cutoff)].groupby(["route", "date"], as_index=False).boardings.sum()
    return result.rename(columns={"route": "unique_id", "date": "ds", "boardings": "y"})


def _replace_special_with_b2(frame: pd.DataFrame, b2: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    result = frame.copy()
    result["prediction"] = result["prediction"].astype(float)
    special = result.date.isin(SPECIAL_DATES)
    lookup = b2.set_index(["route", "date", "hour"]).prediction
    keys = pd.MultiIndex.from_frame(result.loc[special, ["route", "date", "hour"]])
    result.loc[special, "prediction"] = lookup.reindex(keys).to_numpy(dtype=float)
    return result, int(special.sum())


def _forecast_c1(labels: pd.DataFrame, b2: pd.DataFrame, fold: dict) -> tuple[pd.DataFrame, int]:
    cutoff, start, end = map(pd.Timestamp, (fold["train_end"], fold["start"], fold["end"]))
    prediction = _forecast(_c1_input(labels, cutoff), 61)
    extracted = prediction.unique_id.str.extract(r"^(\d+)_(\d{2})$")
    prediction["route"] = extracted[0].astype(int)
    prediction["hour"] = extracted[1].astype(int)
    prediction = prediction.rename(columns={"ds": "date"})
    actual = labels[labels.date.between(start, end)][["route", "date", "hour", "boardings"]]
    result = actual.merge(prediction[["route", "date", "hour", "prediction"]], on=["route", "date", "hour"], validate="one_to_one")
    result, replaced = _replace_special_with_b2(result, b2[b2.fold.eq(fold["id"])])
    result.prediction = result.prediction.clip(lower=0.0)
    return result, replaced


def _forecast_c2(labels: pd.DataFrame, b2: pd.DataFrame, fold: dict) -> tuple[pd.DataFrame, int]:
    cutoff = pd.Timestamp(fold["train_end"])
    prediction = _forecast(_c2_input(labels, cutoff), 61).rename(
        columns={"unique_id": "route", "ds": "date", "prediction": "daily_prediction"}
    )
    prediction.route = prediction.route.astype(int)
    prediction.daily_prediction = prediction.daily_prediction.clip(lower=0.0)
    shape = b2[b2.fold.eq(fold["id"])].copy()
    result = hourly_from_daily(prediction, shape)[["route", "date", "hour", "boardings", "prediction"]]
    result, replaced = _replace_special_with_b2(result, shape)
    return result, replaced


def run(dataset_dir: str, config_path: str, b2_oof_path: str, output_dir: str) -> dict:
    output = Path(output_dir)
    if output.exists():
        raise ValueError("Stats v4 output exists")
    output.mkdir(parents=True)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    labels = load_labels(Path(dataset_dir), "2025-01-01", "2025-09-30")
    b2 = pd.read_csv(b2_oof_path, parse_dates=["date"], float_precision="round_trip")
    results = {}
    for experiment_id, callback in (("C1", _forecast_c1), ("C2", _forecast_c2)):
        parts, folds = [], {}
        for fold in config["folds"]:
            started = time.monotonic()
            frame, replaced = callback(labels, b2, fold)
            frame["fold"] = fold["id"]
            frame["horizon_day"] = (frame.date - pd.Timestamp(fold["start"])).dt.days + 1
            if len(frame) != 9 * 61 * 24 or not np.isfinite(frame.prediction).all():
                raise ValueError(f"Invalid {experiment_id}/{fold['id']} output")
            details = {**_metric(frame), "seconds": time.monotonic() - started, "special_b2_fallback_rows": replaced}
            folds[fold["id"]] = details
            parts.append(frame)
            print(json.dumps({"event": "ets_fold", "id": experiment_id, "fold": fold["id"], "score": details["score"], "seconds": details["seconds"]}), flush=True)
        combined = pd.concat(parts, ignore_index=True)
        combined.to_csv(output / f"{experiment_id}-oof.csv", index=False, encoding="utf-8", lineterminator="\n")
        results[experiment_id] = {"combined": _metric(combined), "folds": folds, "oof_sha256": sha256_file(output / f"{experiment_id}-oof.csv")}
    result = {
        "schema": "score-v4-stats-result",
        "library": "statsforecast", "model": "AutoETS", "model_spec": "ZZZ",
        "season_length": 7, "damped": True,
        "special_date_rule": "use same-origin B2 for official public/transferred holidays and working Saturday; fixed before evaluation",
        "negative_rule": "clip to zero once",
        "representations": {"C1": "216 daily route-hour series", "C2": "9 daily route totals with same-origin B2 hourly shape"},
        "results": results,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "versions": {name: importlib.metadata.version(name) for name in ("statsforecast", "coreforecast", "numpy", "pandas", "scipy")},
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
    args = parser.parse_args()
    print(json.dumps(run(args.dataset_dir, args.config, args.b2_oof, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
