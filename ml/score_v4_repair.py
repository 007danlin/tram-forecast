"""Preserve first-pass evidence and rerun A/B after protocol/code review.

No new hypothesis or parameter search is introduced. Internal B2 forecasts are
read from the first-pass cache; only calibrators and isolated B ablations fit.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from ml.data import load_organizer_labels
from ml.score_v4 import build_internal_b2_oof, sha256_file
from ml.score_v4_study import (
    _evaluate_fold, _load_baseline, _outer_components, _record, _write_json,
)
from ml.score_v4_metrics import summarize_v4
from ml.settings import MODELED_ROUTES


def run(dataset: Path, root: Path, baseline_root: Path, config_path: Path) -> None:
    output = root / "protocol-repair"
    output.mkdir(exist_ok=False)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    original = json.loads((root / "fingerprint.json").read_text(encoding="utf-8"))
    for key, relative in (("labels_train", "labels/labels_day_train.csv"), ("labels_test", "labels/labels_day_test.csv")):
        if sha256_file(dataset / relative) != original["dataset"][key]:
            raise ValueError("Labels changed since first-pass study")
    # Explicit cache symlink: original files remain unmodified and hash-checked.
    (output / "internal-b2").symlink_to((root / "internal-b2").resolve(), target_is_directory=True)
    data = load_organizer_labels(dataset, "2025-01-01", "2025-09-30", routes=MODELED_ROUTES)
    baseline = _load_baseline(baseline_root)
    records = {}
    for experiment_id in ("A1", "A2", "B1", "B2-cal"):
        frames, details = [], []
        for fold in config["folds"]:
            history = data[data.date.between(fold["train_start"], fold["train_end"])].copy()
            actual = data[data.date.between(fold["start"], fold["end"])].copy()
            outer = _outer_components(baseline, fold["id"])
            frame, info = _evaluate_fold(experiment_id, fold, history, actual, outer, config, output)
            frames.append(frame); details.append(info)
        combined = pd.concat(frames, ignore_index=True)
        record = _record(experiment_id, combined, baseline["B2"], config, details)
        record["summary"] = summarize_v4(combined)
        destination = output / "experiments" / experiment_id
        destination.mkdir(parents=True)
        combined.to_csv(destination / "oof.csv", index=False, encoding="utf-8", lineterminator="\n")
        _write_json(destination / "record.json", record)
        old = pd.read_csv(root / "experiments" / experiment_id / "oof.csv", float_precision="round_trip")
        record["max_abs_prediction_change_from_first_pass"] = float(
            abs(old.prediction.to_numpy() - combined.prediction.to_numpy()).max()
        )
        records[experiment_id] = record
        print(json.dumps({"id": experiment_id, "score": record["summary"]["rounded"]["score"]}), flush=True)
    _write_json(output / "complete.json", {
        "reason": "A1 root shrinkage to 1; fixed-origin inner tuning with purged target dates; exact calendar category labels",
        "initial_outputs_preserved": True,
        "experiments": records,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, default=Path("artifacts/score-v4-20260926-r01"))
    parser.add_argument("--baseline-root", type=Path, default=Path("artifacts/score-v3-20260926-r02"))
    parser.add_argument("--config", type=Path, default=Path("ml/experiments/score-v4.json"))
    args = parser.parse_args()
    run(args.dataset_dir, args.study_root, args.baseline_root, args.config)
