"""Two bounded diagnostics for the failed v3 direct model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import sys
import time

import joblib
import numpy as np
import pandas as pd

from ml.data import load_organizer_labels
from ml.score_improvement import assert_same_tasks
from ml.score_v3 import ScoreV3Model, score_v3_config
from ml.score_v4_metrics import summarize_v4
from ml.score_v4 import HorizonBalancedDirectModel, sha256_file
from ml.settings import KEY_COLUMNS, MODELED_ROUTES, TARGET_COLUMN


def _config(experiment_id: str) -> dict:
    return score_v3_config(
        "direct", experiment_id, seed=20250925, threads=4, loss="MAE", target_transform="raw",
        origin_step=5, use_detected_regime=False, use_source_regimes=False,
    )


def _fit_fold(model, data: pd.DataFrame, fold: dict) -> tuple[pd.DataFrame, dict]:
    history = data[data.date.between(fold["train_start"], fold["train_end"])].copy()
    actual = data[data.date.between(fold["start"], fold["end"])].copy()
    started = time.monotonic()
    model.fit(history)
    forecast = model.predict(fold["start"], fold["end"])
    result = actual[[*KEY_COLUMNS, TARGET_COLUMN]].merge(
        forecast[[*KEY_COLUMNS, "prediction", "status"]], on=list(KEY_COLUMNS), validate="one_to_one"
    )
    result["fold"] = fold["id"]
    result["horizon_day"] = (result.date - pd.Timestamp(fold["start"])).dt.days + 1
    if len(result) != len(actual) or not np.isfinite(result.prediction).all() or result.prediction.lt(0).any():
        raise ValueError("Invalid direct-v4 forecast")
    return result, {
        "seconds": time.monotonic() - started,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "fit": model.fit_details_,
    }


def run(dataset_dir: str, config_path: str, baseline_dir: str, output_dir: str) -> dict:
    output = Path(output_dir)
    if output.exists():
        raise ValueError("Direct v4 output exists")
    output.mkdir(parents=True)
    study = json.loads(Path(config_path).read_text(encoding="utf-8"))
    data = load_organizer_labels(dataset_dir, "2025-01-01", "2025-10-31", routes=MODELED_ROUTES)
    baseline_root = Path(baseline_dir)
    baseline = pd.read_csv(baseline_root / "experiments" / "B2" / "oof.csv", parse_dates=["date"], float_precision="round_trip")
    old_direct = pd.read_csv(baseline_root / "experiments" / "D-MAE" / "oof.csv", parse_dates=["date"], float_precision="round_trip")
    results = {}
    for experiment_id, model_type in (("D1", ScoreV3Model), ("D2", HorizonBalancedDirectModel)):
        parts, fit = [], []
        for fold in study["folds"]:
            model = model_type(_config(experiment_id))
            frame, details = _fit_fold(model, data, fold)
            destination = output / "folds" / experiment_id / fold["id"]
            destination.mkdir(parents=True)
            frame.to_csv(destination / "oof.csv", index=False, encoding="utf-8", lineterminator="\n")
            joblib.dump(model, destination / "model.joblib", compress=3)
            (destination / "record.json").write_text(json.dumps({
                "details": details, "oof_sha256": sha256_file(destination / "oof.csv"),
                "model_sha256": sha256_file(destination / "model.joblib"),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            parts.append(frame); fit.append(details)
            print(json.dumps({"event": "direct_fold", "id": experiment_id, "fold": fold["id"], "seconds": details["seconds"]}), flush=True)
        combined = pd.concat(parts, ignore_index=True)
        assert_same_tasks(baseline, combined)
        combined.to_csv(output / f"{experiment_id}-oof.csv", index=False, encoding="utf-8", lineterminator="\n")
        results[experiment_id] = {"summary": summarize_v4(combined), "fit": fit, "oof_sha256": sha256_file(output / f"{experiment_id}-oof.csv")}
    result = {
        "schema": "score-v4-direct-result",
        "D1": "v3 D-MAE with only origin_step 14 -> 5",
        "D2": "D1 plus grid-only equal effective horizon mass after inverse-duplicate weighting",
        "controls": {"B2": summarize_v4(baseline), "v3_D_MAE": summarize_v4(old_direct)},
        "results": results,
    }
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--config", default="ml/experiments/score-v4.json")
    parser.add_argument("--baseline-dir", default="artifacts/score-v3-20260926-r02")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.dataset_dir, args.config, args.baseline_dir, args.output)
    print(json.dumps({"output": args.output, "scores": {key: value["summary"]["rounded"]["score"] for key, value in result["results"].items()}}))


if __name__ == "__main__":
    main()
