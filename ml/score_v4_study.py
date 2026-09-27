"""Bounded score-v4 experiment runner.

The initial stage evaluates A1/A2/B1/B2-cal on the frozen S1--S4 protocol.
It reuses the already verified incumbent OOF and creates honest, cached internal
B2 forecasts for calibrator training.  D and stress windows are intentionally
not opened during this stage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

import joblib
import numpy as np
import pandas as pd

from ml.data import load_organizer_labels
from ml.score_improvement import assert_same_tasks, guardrail, metrics
from ml.score_v3_study import unique_date_diagnostic
from ml.score_v4_metrics import summarize_v4
from ml.score_v4 import (
    HourlyResidualCalibrator,
    V4B2AblationModel,
    attach_origin_features,
    build_internal_b2_oof,
    fit_a1,
    sha256_file,
)
from ml.settings import KEY_COLUMNS, MODELED_ROUTES, TARGET_COLUMN


EXPECTED_B2_OOF_SHA256 = "9bb89c52ca7a2670c7308e7f82fd29fff6d1bc0125ee9d65d7a2769939c5bce5"
INITIAL_IDS = ("A1", "A2", "B1", "B2-cal")


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.write("\n")


def validate_config(config: dict) -> None:
    if config.get("schema") != "score-v4-study" or config.get("new_configuration_limit") != 12:
        raise ValueError("Invalid score-v4 schema or configuration cap")
    if not 1 <= config.get("threads", 0) <= 4 or len(config.get("folds", [])) != 4:
        raise ValueError("score-v4 requires four S folds and 1..4 threads")
    for fold in [*config["folds"], *config["stress_folds"], config["diagnostic"]]:
        start, end, cutoff = pd.Timestamp(fold["start"]), pd.Timestamp(fold["end"]), pd.Timestamp(fold["train_end"])
        if start != cutoff + pd.Timedelta(days=1) or (end - start).days != 60:
            raise ValueError(f"Non-contiguous or non-61-day fold: {fold['id']}")
        if end > pd.Timestamp("2025-10-31"):
            raise ValueError("score-v4 validation may not use targets after October")
    internal = config["internal_oof"]
    if internal != {"origin_step_days": 5, "minimum_history_days": 60, "minimum_target_days": 14, "horizon_days": 61}:
        raise ValueError("The preregistered internal-origin grid changed")


def _fingerprint(config: dict, dataset: Path, baseline_root: Path) -> dict:
    root = Path(__file__).resolve().parent.parent
    sources = [
        root / "ml" / "score_v4.py", root / "ml" / "score_v4_study.py",
        root / "ml" / "model.py", root / "ml" / "factors.py", root / "ml" / "data.py",
        root / "ml" / "experiments" / "score-v4.json",
    ]
    dependencies = {}
    for package in ("numpy", "pandas", "scikit-learn", "catboost", "joblib", "threadpoolctl"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    fields = {
        "config": config,
        "sources": {str(path.relative_to(root)): sha256_file(path) for path in sources},
        "dataset": {
            "labels_train": sha256_file(dataset / "labels" / "labels_day_train.csv"),
            "labels_test": sha256_file(dataset / "labels" / "labels_day_test.csv"),
            "sample": sha256_file(dataset / "test_submission.csv"),
        },
        "baseline_oof": sha256_file(baseline_root / "experiments" / "B2" / "oof.csv"),
        "python": sys.version,
        "platform": platform.platform(),
        "dependencies": dependencies,
    }
    return {"fingerprint": _digest(fields), **fields}


def _initialize(output: Path, fingerprint: dict, *, resume: bool) -> None:
    if output.exists():
        if not resume:
            raise ValueError("Output exists; choose a new directory or pass --resume")
        saved = json.loads((output / "fingerprint.json").read_text(encoding="utf-8"))
        if saved != fingerprint:
            raise ValueError("Resume fingerprint mismatch")
        return
    if resume:
        raise ValueError("Cannot resume an absent score-v4 run")
    output.mkdir(parents=True)
    _write_json(output / "fingerprint.json", fingerprint)
    (output / "initial.diff").write_bytes(subprocess.check_output(["git", "diff", "HEAD"]))


def _load_baseline(root: Path) -> dict[str, pd.DataFrame]:
    result = {}
    for name in ("B0", "B1", "B2"):
        path = root / "experiments" / name / "oof.csv"
        frame = pd.read_csv(path, parse_dates=["date"], float_precision="round_trip")
        result[name] = frame
    if sha256_file(root / "experiments" / "B2" / "oof.csv") != EXPECTED_B2_OOF_SHA256:
        raise ValueError("Exact B2 OOF checksum mismatch")
    for frame in result.values():
        assert_same_tasks(result["B2"], frame)
    return result


def _outer_components(baseline: dict[str, pd.DataFrame], fold_id: str) -> pd.DataFrame:
    keys = [*KEY_COLUMNS, TARGET_COLUMN, "fold", "horizon_day"]
    result = baseline["B2"].loc[baseline["B2"].fold.eq(fold_id), keys + ["prediction"]].rename(columns={"prediction": "b2"})
    for name, column in (("B0", "b0"), ("B1", "b1")):
        part = baseline[name].loc[baseline[name].fold.eq(fold_id), [*KEY_COLUMNS, "prediction"]].rename(columns={"prediction": column})
        result = result.merge(part, on=list(KEY_COLUMNS), validate="one_to_one")
    return result


def _save_fold(output: Path, experiment_id: str, fold_id: str, frame: pd.DataFrame, model: object, details: dict) -> None:
    destination = output / "folds" / experiment_id / fold_id
    destination.mkdir(parents=True, exist_ok=False)
    frame.to_csv(destination / "oof.csv", index=False, encoding="utf-8", lineterminator="\n")
    joblib.dump(model, destination / "model.joblib", compress=3)
    _write_json(destination / "record.json", {
        "id": experiment_id, "fold": fold_id, "rows": len(frame),
        "oof_sha256": sha256_file(destination / "oof.csv"),
        "model_sha256": sha256_file(destination / "model.joblib"),
        "details": details,
    })


def _load_fold(output: Path, experiment_id: str, fold_id: str) -> tuple[pd.DataFrame, dict]:
    destination = output / "folds" / experiment_id / fold_id
    record = json.loads((destination / "record.json").read_text(encoding="utf-8"))
    if record["oof_sha256"] != sha256_file(destination / "oof.csv") or record["model_sha256"] != sha256_file(destination / "model.joblib"):
        raise ValueError(f"Invalid fold cache: {experiment_id}/{fold_id}")
    return pd.read_csv(destination / "oof.csv", parse_dates=["date"], float_precision="round_trip"), record["details"]


def _metric_frame(base: pd.DataFrame, prediction: np.ndarray, experiment_id: str) -> pd.DataFrame:
    result = base[[*KEY_COLUMNS, TARGET_COLUMN, "fold", "horizon_day"]].copy()
    result["prediction"] = np.maximum(np.asarray(prediction, dtype=float), 0.0)
    result["status"] = "ok"
    if len(result) != len(base) or not np.isfinite(result.prediction).all():
        raise ValueError(f"Invalid prediction from {experiment_id}")
    return result


def _evaluate_fold(
    experiment_id: str,
    fold: dict,
    history: pd.DataFrame,
    actual: pd.DataFrame,
    outer: pd.DataFrame,
    config: dict,
    output: Path,
) -> tuple[pd.DataFrame, dict]:
    if (output / "folds" / experiment_id / fold["id"]).exists():
        return _load_fold(output, experiment_id, fold["id"])
    started = time.monotonic()
    if experiment_id in ("A1", "A2"):
        internal, audit = build_internal_b2_oof(history, config["internal_oof"], output / "internal-b2" / fold["id"])
        featured = attach_origin_features(
            outer, history, down=config["a1"]["state_down"], up=config["a1"]["state_up"]
        )
        if experiment_id == "A1":
            model, tuning = fit_a1(internal, config["a1"])
            prediction = featured.b2.to_numpy(dtype=float) * model.predict_factor(featured)
            details = {"internal_oof": audit, "tuning": tuning}
        else:
            model = HourlyResidualCalibrator(config["a2"]).fit(internal)
            prediction = model.predict(featured)
            details = {"internal_oof": audit, "fit": model.fit_details_}
    else:
        mode = "seasonal_portable" if experiment_id == "B1" else "day_type"
        model = V4B2AblationModel(mode).fit(history)
        forecast = model.predict(fold["start"], fold["end"])
        merged = actual[[*KEY_COLUMNS, TARGET_COLUMN]].merge(
            forecast[[*KEY_COLUMNS, "prediction"]], on=list(KEY_COLUMNS), validate="one_to_one"
        )
        prediction = merged.prediction.to_numpy(dtype=float)
        details = {"features": model.feature_manifest_}
    frame = _metric_frame(outer, prediction, experiment_id)
    details.update({
        "seconds": time.monotonic() - started,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "train_end": fold["train_end"],
    })
    _save_fold(output, experiment_id, fold["id"], frame, model, details)
    print(json.dumps({"event": "fold_complete", "id": experiment_id, "fold": fold["id"], "seconds": details["seconds"]}), flush=True)
    return frame, details


def _record(experiment_id: str, frame: pd.DataFrame, baseline: pd.DataFrame, config: dict, fit: list[dict]) -> dict:
    summary = summarize_v4(frame)
    admission = guardrail(frame, baseline, config["thresholds"])
    return {
        "id": experiment_id,
        "hypothesis": {
            "A1": "A shrunk past-only level calibration of honest B2 OOF reduces daily-level error.",
            "A2": "A compact hourly residual model over honest B2 component OOF improves level and shape.",
            "B1": "Removing categorical month/week improves seasonal extrapolation without changing B2 fitting policy.",
            "B2-cal": "Official-day-type interactions improve transfer while working Saturday uses a fixed weekday-profile rule.",
        }[experiment_id],
        "summary": summary,
        "unique_date_diagnostic": unique_date_diagnostic(frame),
        "admission": admission,
        "decision": "eligible" if admission["passed"] else "rejected",
        "fit": fit,
        "platform_score": None,
    }


def _journal(records: dict[str, dict], baseline_summary: dict, path: Path) -> None:
    base_score = baseline_summary["rounded"]["score"]
    rows = [{
        "id": "B2", "hypothesis": "Frozen incumbent control", "rounded_score": base_score,
        "delta_score": 0.0, "sae": baseline_summary["rounded"]["absolute_error"], "bias": baseline_summary["rounded"]["signed_bias"],
        "decision": "champion_control", "platform_score": 0.84260,
    }]
    for record in records.values():
        rounded = record["summary"]["rounded"]
        rows.append({
            "id": record["id"], "hypothesis": record["hypothesis"], "rounded_score": rounded["score"],
            "delta_score": rounded["score"] - base_score, "sae": rounded["absolute_error"], "bias": rounded["signed_bias"],
            "decision": record["decision"], "platform_score": None,
        })
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def run_initial(dataset_dir: str, config_path: str, baseline_dir: str, output_dir: str, *, resume: bool = False) -> dict:
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Use Python 3.12 for score-v4")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    validate_config(config)
    dataset, baseline_root, output = Path(dataset_dir), Path(baseline_dir), Path(output_dir)
    fingerprint = _fingerprint(config, dataset, baseline_root)
    _initialize(output, fingerprint, resume=resume)
    complete = output / "initial-complete.json"
    if complete.exists():
        return json.loads(complete.read_text(encoding="utf-8"))
    data = load_organizer_labels(dataset, "2025-01-01", "2025-10-31", routes=MODELED_ROUTES)
    baseline = _load_baseline(baseline_root)
    baseline_oof = baseline["B2"].copy()
    records = {}
    for experiment_id in INITIAL_IDS:
        parts, fit = [], []
        for fold in config["folds"]:
            history = data[data.date.between(fold["train_start"], fold["train_end"])].copy()
            actual = data[data.date.between(fold["start"], fold["end"])].copy()
            outer = _outer_components(baseline, fold["id"])
            frame, details = _evaluate_fold(experiment_id, fold, history, actual, outer, config, output)
            parts.append(frame)
            fit.append(details)
        combined = pd.concat(parts, ignore_index=True)
        assert_same_tasks(baseline_oof, combined)
        record = _record(experiment_id, combined, baseline_oof, config, fit)
        destination = output / "experiments" / experiment_id
        destination.mkdir(parents=True, exist_ok=True)
        combined.to_csv(destination / "oof.csv", index=False, encoding="utf-8", lineterminator="\n")
        _write_json(destination / "record.json", record)
        records[experiment_id] = record
        print(json.dumps({"event": "experiment_complete", "id": experiment_id, "score": record["summary"]["rounded"]["score"], "decision": record["decision"]}), flush=True)
    baseline_summary = summarize_v4(baseline_oof)
    _journal(records, baseline_summary, output / "experiment-journal.csv")
    result = {
        "schema": "score-v4-initial-result",
        "fingerprint": fingerprint["fingerprint"],
        "baseline": {"id": "B2", "oof_sha256": EXPECTED_B2_OOF_SHA256, "summary": baseline_summary, "platform_score": 0.84260},
        "experiments": records,
        "selection_data": "S1-S4 only; overlapping 61-day folds; D and stress windows unopened",
        "configuration_count": len(INITIAL_IDS),
        "configuration_limit": config["new_configuration_limit"],
        "platform_upload": "not_performed",
        "server_update": "not_performed",
    }
    _write_json(complete, result, exclusive=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--config", default="ml/experiments/score-v4.json")
    parser.add_argument("--baseline-dir", default="artifacts/score-v3-20260926-r02")
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run_initial(args.dataset_dir, args.config, args.baseline_dir, args.output, resume=args.resume)
    print(json.dumps({"output": args.output, "fingerprint": result["fingerprint"], "experiments": list(result["experiments"])}))


if __name__ == "__main__":
    main()
