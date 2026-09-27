"""Preregistered v4.1 experiment: project A2 hourly shape onto B2 daily volume."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.score_improvement import assert_same_tasks, guardrail
from ml.score_v4_metrics import summarize_v4


KEYS = ["fold", "route", "date", "hour"]
DAY_KEYS = ["fold", "route", "date"]


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def project_shape(baseline: pd.DataFrame, shape: pd.DataFrame) -> pd.DataFrame:
    """Preserve each B2 float day total and replace only the hourly allocation.

    Boardings are carried solely for evaluation and never enter the transform.
    A zero/non-finite shape sum falls back to the exact baseline hours.
    """
    assert_same_tasks(shape, baseline)
    if baseline[KEYS].duplicated().any() or shape[KEYS].duplicated().any():
        raise ValueError("Duplicate forecast tasks")
    result = baseline.copy()
    b2 = baseline.prediction.to_numpy(dtype=float)
    a2 = np.maximum(shape.prediction.to_numpy(dtype=float), 0.0)
    if not np.isfinite(b2).all() or not np.isfinite(a2).all() or (b2 < 0).any():
        raise ValueError("Forecasts must be finite and nonnegative")
    group = baseline.groupby(DAY_KEYS, sort=False).ngroup().to_numpy()
    b2_total = pd.Series(b2).groupby(group, sort=False).transform("sum").to_numpy()
    a2_total = pd.Series(a2).groupby(group, sort=False).transform("sum").to_numpy()
    projected = np.divide(b2_total * a2, a2_total, out=b2.copy(), where=a2_total > 0)
    result["prediction"] = projected
    return result


def _record(name: str, frame: pd.DataFrame, baseline: pd.DataFrame, config_path: Path, source_path: Path) -> dict:
    admission = guardrail(frame, baseline, json.loads(config_path.read_text(encoding="utf-8"))["thresholds"])
    return {
        "id": name,
        "config_sha256": sha256_file(config_path),
        "source_sha256": sha256_file(source_path),
        "oof_sha256": None,
        "summary": summarize_v4(frame),
        "admission": admission,
        "decision": "eligible_for_frozen_diagnostics" if admission["passed"] else "rejected_on_S",
    }


def run(baseline_path: Path, shape_path: Path, config_path: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    baseline = pd.read_csv(baseline_path, parse_dates=["date"], float_precision="round_trip")
    shape = pd.read_csv(shape_path, parse_dates=["date"], float_precision="round_trip")
    assert_same_tasks(shape, baseline)
    p1 = project_shape(baseline, shape)
    p2 = baseline.copy()
    p2["prediction"] = 0.5 * baseline.prediction.to_numpy(dtype=float) + 0.5 * p1.prediction.to_numpy(dtype=float)
    records = {}
    for name, frame in (("P1", p1), ("P2", p2)):
        destination = output / name
        destination.mkdir()
        oof = destination / "oof.csv"
        frame.to_csv(oof, index=False, encoding="utf-8", lineterminator="\n")
        record = _record(name, frame, baseline, config_path, Path(__file__))
        record["oof_sha256"] = sha256_file(oof)
        (destination / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records[name] = record
    passed = [name for name, record in records.items() if record["admission"]["passed"]]
    winner = max(passed, key=lambda name: (records[name]["summary"]["rounded"]["score"], name == "P2")) if passed else "B2"
    result = {
        "schema": "score-v4.1-result-v1",
        "baseline_path": str(baseline_path),
        "baseline_sha256": sha256_file(baseline_path),
        "shape_path": str(shape_path),
        "shape_sha256": sha256_file(shape_path),
        "config_path": str(config_path),
        "config_sha256": sha256_file(config_path),
        "source_sha256": sha256_file(Path(__file__)),
        "records": records,
        "winner_after_S": winner,
        "budget_used": 2,
        "stopped": winner == "B2",
        "reason": "Neither candidate passed unchanged S guardrails" if winner == "B2" else "Frozen finalist proceeds to diagnostic D/stress",
    }
    (output / "complete.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {"score": record["summary"]["rounded"]["score"], "admission": record["admission"]} for name, record in records.items()}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=Path("artifacts/score-v3-20260926-r02/experiments/B2/oof.csv"))
    parser.add_argument("--shape", type=Path, default=Path("artifacts/score-v4-20260926-r01/protocol-repair/experiments/A2/oof.csv"))
    parser.add_argument("--config", type=Path, default=Path("ml/experiments/score-v41.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/score-v41-20260927-r01"))
    args = parser.parse_args()
    run(args.baseline, args.shape, args.config, args.output)
