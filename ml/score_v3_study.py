"""Reproducible, origin-safe score-v3 experiment study.

Selection uses four fixed 61-day windows.  The reused September--October
period is evaluated once, only after the selected configuration is frozen.
Large raw CSV files are not loaded here; the verified organizer labels are the
training target and the separate streaming audit covers raw/label agreement.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.artifact import create_artifact, sha256_file, submission_preflight, write_submission
from ml.data import load_organizer_labels
from ml.model import build_hgbt_model
from ml.score_improvement import assert_same_tasks, block_uncertainty, guardrail, metrics
from ml.score_v3 import _calendar, score_v3_config
from ml.settings import KEY_COLUMNS, MODELED_ROUTES, TARGET_COLUMN


EXPECTED_CONTROL_SCORES = {
    "S1": 0.8779084257160926,
    "S2": 0.8424445775629517,
    "S3": 0.8228329111812005,
    "S4": 0.8341152403485839,
    "combined": 0.8448414816898706,
    "D": 0.8290094281374523,
}


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.write("\n")


def _study_fingerprint(config: dict, dataset: Path) -> dict:
    root = Path(__file__).resolve().parent.parent
    source_paths = [
        *sorted((root / "ml").glob("*.py")),
        *sorted((root / "ml").glob("requirements*.txt")),
        root / "scripts" / "audit_route_regimes.py",
        root / "scripts" / "audit_score_context.py",
    ]
    data_paths = {
        "README.md": dataset / "README.md",
        "labels/labels_day_train.csv": dataset / "labels" / "labels_day_train.csv",
        "labels/labels_day_test.csv": dataset / "labels" / "labels_day_test.csv",
        "test_submission.csv": dataset / "test_submission.csv",
    }
    dependencies = {}
    for package in ("numpy", "pandas", "scikit-learn", "scipy", "joblib", "threadpoolctl", "catboost"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    fields = {
        "config": config,
        "sources": {str(path.relative_to(root)): sha256_file(path) for path in source_paths},
        "data": {name: sha256_file(path) for name, path in data_paths.items()},
        "dependencies": dependencies,
        "python": sys.version,
        "platform": platform.platform(),
    }
    return {"fingerprint": _digest(fields), **fields}


def _initialize(output: Path, fingerprint: dict, *, resume: bool) -> None:
    if output.exists():
        if not resume:
            raise ValueError("Output exists; choose a new directory or use validated --resume")
        saved = json.loads((output / "fingerprint.json").read_text(encoding="utf-8"))
        if saved != fingerprint:
            raise ValueError("Resume fingerprint mismatch")
        return
    if resume:
        raise ValueError("Cannot resume an absent run")
    output.mkdir(parents=True)
    _write_json(output / "fingerprint.json", fingerprint)
    _write_json(output / "config.json", fingerprint["config"])
    (output / "initial.diff").write_bytes(subprocess.check_output(["git", "diff", "HEAD"]))


def _slice_metrics(data: pd.DataFrame, column: str) -> dict:
    return {str(value): metrics(part) for value, part in data.groupby(column, sort=True, observed=True)}


def summarize_v3(frame: pd.DataFrame) -> dict:
    data = _calendar(frame.copy())
    data["horizon"] = pd.cut(
        data["horizon_day"], [0, 7, 30, 61], labels=["1-7", "8-30", "31-61"]
    ).astype(str)
    data["weekpart"] = np.where(data["is_day_off"].eq(1), "day_off", "workday")
    hourly_error = float(np.abs(data[TARGET_COLUMN] - np.floor(data["prediction"] + 0.5)).sum())
    daily = data.groupby(["fold", "route", "date"], as_index=False, observed=True).agg(
        y=(TARGET_COLUMN, "sum"), prediction=("prediction", "sum")
    )
    daily["rounded_prediction"] = np.floor(daily["prediction"] + 0.5)
    daily["absolute_error"] = np.abs(daily["y"] - daily["rounded_prediction"])
    daily_error = float(daily["absolute_error"].sum())
    low = daily["y"].le(1_000)
    return {
        "rounded": metrics(data),
        "unrounded": metrics(data, rounded=False),
        "unique_dates": int(data["date"].nunique()),
        "daily": {
            "absolute_error": daily_error,
            "hourly_absolute_error": hourly_error,
            "level_error_share_of_hourly_sae": daily_error / hourly_error if hourly_error else None,
            "signed_bias": float((daily["rounded_prediction"] - daily["y"]).sum()),
            "low_volume_threshold": 1_000,
            "low_volume_days": int(low.sum()),
            "low_volume_absolute_error": float(daily.loc[low, "absolute_error"].sum()),
        },
        "slices": {
            column: _slice_metrics(data, column)
            for column in ("fold", "route", "hour", "weekpart", "effective_day_type", "horizon")
        },
    }


def unique_date_diagnostic(frame: pd.DataFrame) -> dict:
    # A target key can occur in several overlapping folds.  The fixed rule keeps
    # the forecast made at the latest available origin (smallest horizon).
    ordered = frame.sort_values([*KEY_COLUMNS, "horizon_day", "fold"])
    unique = ordered.drop_duplicates(list(KEY_COLUMNS), keep="first").reset_index(drop=True)
    return {
        "rule": "latest available origin, implemented as minimum horizon_day per route/date/hour",
        "rows": len(unique),
        "dates": int(unique["date"].nunique()),
        "rounded": metrics(unique),
        "unrounded": metrics(unique, rounded=False),
    }


def _fit_one(data: pd.DataFrame, config: dict, fold: dict, threads: int):
    history = data[data["date"].between(fold["train_start"], fold["train_end"])].copy()
    actual = data[data["date"].between(fold["start"], fold["end"])].copy()
    started = time.monotonic()
    with threadpool_limits(limits=threads):
        model = build_hgbt_model(config["model_name"], config)
        model.fit(history)
        prediction = model.predict(fold["start"], fold["end"])
    result = actual[[*KEY_COLUMNS, TARGET_COLUMN]].merge(
        prediction[[*KEY_COLUMNS, "prediction", "status"]],
        on=list(KEY_COLUMNS),
        validate="one_to_one",
    )
    if len(result) != len(actual) or not np.isfinite(result["prediction"]).all() or result["prediction"].lt(0).any():
        raise ValueError("Incomplete, negative, or non-finite score-v3 forecast")
    result["fold"] = fold["id"]
    result["horizon_day"] = (result["date"] - pd.Timestamp(fold["start"])).dt.days + 1
    details = {
        "seconds": time.monotonic() - started,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "model": getattr(model, "fit_details_", {}),
        "thread_limit": threads,
    }
    return model, result, details


class Study:
    def __init__(self, data: pd.DataFrame, config: dict, output: Path, fingerprint: str):
        self.data = data
        self.config = config
        self.output = output
        self.fingerprint = fingerprint
        self.frames: dict[str, pd.DataFrame] = {}
        self.records: dict[str, dict] = {}

    def evaluate(self, spec: dict, folds: list[dict] | None = None, *, diagnostic: bool = False) -> pd.DataFrame:
        experiment_id = spec["id"]
        model_config = spec["config"]
        selected_folds = self.config["folds"] if folds is None else folds
        parts, fit_details = [], []
        for fold in selected_folds:
            target = self.output / "folds" / experiment_id / fold["id"]
            identity = _digest({
                "run": self.fingerprint,
                "id": experiment_id,
                "config": model_config,
                "fold": fold,
            })
            if target.exists():
                record = json.loads((target / "record.json").read_text(encoding="utf-8"))
                if record["identity"] != identity or sha256_file(target / "oof.csv") != record["oof_sha256"]:
                    raise ValueError(f"Invalid fold cache: {experiment_id}/{fold['id']}")
                part = pd.read_csv(target / "oof.csv", parse_dates=["date"], float_precision="round_trip")
                details = record["fit"]
            else:
                model, part, details = _fit_one(self.data, model_config, fold, self.config["threads"])
                target.parent.mkdir(parents=True, exist_ok=True)
                pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=target.parent))
                try:
                    part.to_csv(pending / "oof.csv", index=False)
                    joblib.dump(model, pending / "model.joblib", compress=3)
                    _write_json(pending / "record.json", {
                        "identity": identity,
                        "config": model_config,
                        "fold": fold,
                        "fit": details,
                        "oof_sha256": sha256_file(pending / "oof.csv"),
                        "model_sha256": sha256_file(pending / "model.joblib"),
                    })
                    pending.rename(target)
                finally:
                    if pending.exists():
                        import shutil
                        shutil.rmtree(pending)
                print(json.dumps({"event": "fold_complete", "id": experiment_id, "fold": fold["id"], **details}, default=str), flush=True)
            parts.append(part)
            fit_details.append(details)
        frame = pd.concat(parts, ignore_index=True)
        if diagnostic:
            return frame
        self._record(spec, frame, fit_details)
        return frame

    def _record(self, spec: dict, frame: pd.DataFrame, fit_details: list[dict], *, reused_oof: list[str] | None = None) -> None:
        experiment_id = spec["id"]
        summary = summarize_v3(frame)
        admission = None
        if "B2" in self.frames and experiment_id not in ("B0", "B1", "B2"):
            admission = guardrail(frame, self.frames["B2"], self.config["thresholds"])
        decision = "control" if experiment_id in ("B0", "B1", "B2") else ("eligible" if admission and admission["passed"] else "rejected")
        record = {
            "id": experiment_id,
            "hypothesis": spec["hypothesis"],
            "change": spec["change"],
            "config": spec["config"],
            "config_hash": _digest(spec["config"]),
            "run_fingerprint": self.fingerprint,
            "summary": summary,
            "unique_date_diagnostic": unique_date_diagnostic(frame),
            "admission": admission,
            "decision": decision,
            "fit": fit_details,
            "reused_oof": reused_oof,
            "platform_score": None,
        }
        destination = self.output / "experiments" / experiment_id
        if destination.exists():
            saved = json.loads((destination / "record.json").read_text(encoding="utf-8"))
            if saved != record or sha256_file(destination / "oof.csv") != (destination / "oof.sha256").read_text().strip():
                raise ValueError(f"Experiment cache mismatch: {experiment_id}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination.parent))
            try:
                frame.to_csv(pending / "oof.csv", index=False)
                (pending / "oof.sha256").write_text(sha256_file(pending / "oof.csv") + "\n", encoding="utf-8")
                _write_json(pending / "record.json", record)
                pending.rename(destination)
            finally:
                if pending.exists():
                    import shutil
                    shutil.rmtree(pending)
        self.frames[experiment_id] = frame
        self.records[experiment_id] = record
        print(json.dumps({"event": "experiment_complete", "id": experiment_id, "score": summary["rounded"]["score"], "decision": decision}), flush=True)

    def blend(self, experiment_id: str, candidate_id: str, candidate_weight: float) -> None:
        baseline, candidate = self.frames["B2"], self.frames[candidate_id]
        assert_same_tasks(baseline, candidate)
        result = baseline.copy()
        result["prediction"] = (1.0 - candidate_weight) * baseline["prediction"] + candidate_weight * candidate["prediction"]
        spec = {
            "id": experiment_id,
            "hypothesis": "A fixed blend can reduce complementary B2 and origin-model errors without target-dependent calibration.",
            "change": f"Blend B2 with {candidate_id}; candidate weight={candidate_weight:.2f}.",
            "config": score_v3_config(
                "blend", experiment_id,
                components=[self.records["B2"]["config"], self.records[candidate_id]["config"]],
                weights=[1.0 - candidate_weight, candidate_weight],
                seed=self.config["seed"], threads=self.config["threads"],
            ),
        }
        self._record(spec, result, [{"seconds": 0.0, "reused_oof": ["B2", candidate_id]}], reused_oof=["B2", candidate_id])


def _model_spec(experiment_id: str, kind: str, hypothesis: str, change: str, common: dict, **kwargs) -> dict:
    return {
        "id": experiment_id,
        "hypothesis": hypothesis,
        "change": change,
        "config": score_v3_config(kind, experiment_id, **common, **kwargs),
    }


def _control_specs(common: dict) -> list[dict]:
    return [
        _model_spec("B0", "current_calendar", "Reproduce the former calendar control.", "No change; control only.", common),
        _model_spec("B1", "current_interaction", "Reproduce the interaction component.", "No change; control only.", common),
        _model_spec("B2", "current_ensemble", "Reproduce the current 0.96-scaled ensemble.", "No change; selection baseline.", common),
    ]


def _initial_specs(common: dict) -> list[dict]:
    specs = [
        _model_spec("F1-B0", "current_calendar", "Using all permitted rows may improve B0 because auto early stopping reached the iteration limit.", "Only early_stopping=False.", common, component_early_stopping=False),
        _model_spec("F1-B1", "current_interaction", "Using all permitted rows may improve B1 because auto early stopping reached the iteration limit.", "Only early_stopping=False.", common, component_early_stopping=False),
        _model_spec("F1-B2", "current_ensemble", "Full-fit components may improve the existing ensemble.", "Only early_stopping=False for both B2 components.", common, component_early_stopping=False),
    ]
    for loss in ("MAE", "RMSE"):
        specs.append(_model_spec(
            f"D-{loss}", "direct",
            f"A direct 61-day origin model with {loss} can track changing demand better than B2.",
            f"Direct CatBoost; {loss}; origin aggregates; no detected/source regime flag.",
            common, loss=loss, target_transform="raw", use_detected_regime=False, use_source_regimes=False,
        ))
    for transform in ("residual", "ratio"):
        for loss in ("MAE", "RMSE"):
            specs.append(_model_spec(
                f"L-{transform}-{loss}", "daily",
                f"A daily {transform} correction with {loss} plus normalized hourly shares can reduce level error.",
                f"Daily CatBoost {transform}/{loss}; recent origin levels; normalized shrunk hourly shares; no regime flag.",
                common, loss=loss, target_transform=transform, use_detected_regime=False, use_source_regimes=False,
            ))
    return specs


def _winner(records: dict[str, dict], ids: list[str], *, require_admission: bool) -> str | None:
    options = [records[name] for name in ids if name in records]
    if require_admission:
        options = [record for record in options if record["admission"] and record["admission"]["passed"]]
    if not options:
        return None
    return max(options, key=lambda record: (record["summary"]["rounded"]["score"], record["id"]))["id"]


def _journal(records: dict[str, dict], path: Path) -> None:
    rows = []
    for record in records.values():
        rows.append({
            "id": record["id"],
            "hypothesis": record["hypothesis"],
            "change": record["change"],
            "rounded_score": record["summary"]["rounded"]["score"],
            "unrounded_score": record["summary"]["unrounded"]["score"],
            "sae": record["summary"]["rounded"]["absolute_error"],
            "sum_y": record["summary"]["rounded"]["sum_y"],
            "bias": record["summary"]["rounded"]["signed_bias"],
            "daily_error_share": record["summary"]["daily"]["level_error_share_of_hourly_sae"],
            "decision": record["decision"],
            "reasons": "|".join((record["admission"] or {}).get("reasons", [])),
            "config_hash": record["config_hash"],
            "platform_score": None,
        })
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def validate_study_config(config: dict) -> None:
    if config.get("schema") != "score-v3-study" or not 1 <= config.get("threads", 0) <= 4:
        raise ValueError("Invalid score-v3 study config")
    if len(config.get("folds", [])) != 4 or len({fold["id"] for fold in config["folds"]}) != 4:
        raise ValueError("Exactly four unique selection folds are required")
    for fold in [*config["folds"], config["diagnostic"]]:
        if pd.Timestamp(fold["start"]) != pd.Timestamp(fold["train_end"]) + pd.Timedelta(days=1):
            raise ValueError("Every target window must start after its cutoff")
        if (pd.Timestamp(fold["end"]) - pd.Timestamp(fold["start"])).days != 60:
            raise ValueError("Every target window must contain exactly 61 days")
        if pd.Timestamp(fold["end"]) > pd.Timestamp("2025-10-31"):
            raise ValueError("Forbidden target after October")
    if config.get("new_training_config_limit") != 24:
        raise ValueError("The v3 primary-search cap must remain 24")


def run_study(dataset_dir: str, config_path: str, output_dir: str, *, resume: bool = False) -> dict:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    validate_study_config(config)
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Use Python 3.12 for score-v3")
    dataset, output = Path(dataset_dir), Path(output_dir)
    fingerprint = _study_fingerprint(config, dataset)
    _initialize(output, fingerprint, resume=resume)
    completed = output / "complete.json"
    if completed.exists():
        return json.loads(completed.read_text(encoding="utf-8"))
    data = load_organizer_labels(dataset, "2025-01-01", "2025-10-31")
    data = data[data["route"].isin(MODELED_ROUTES)].copy()
    common = {"seed": config["seed"], "threads": config["threads"]}
    study = Study(data, config, output, fingerprint["fingerprint"])

    for spec in _control_specs(common):
        study.evaluate(spec)
    for fold, expected in ((fold, EXPECTED_CONTROL_SCORES[fold["id"]]) for fold in config["folds"]):
        observed = study.records["B2"]["summary"]["slices"]["fold"][fold["id"]]["score"]
        if not np.isclose(observed, expected, atol=1e-12, rtol=0):
            raise ValueError(f"B2 control mismatch for {fold['id']}: {observed} != {expected}")
    combined = study.records["B2"]["summary"]["rounded"]["score"]
    if not np.isclose(combined, EXPECTED_CONTROL_SCORES["combined"], atol=1e-12, rtol=0):
        raise ValueError(f"Combined B2 control mismatch: {combined}")

    trained = 0
    initial = _initial_specs(common)
    for spec in initial:
        study.evaluate(spec)
        trained += 1

    direct_ids = [spec["id"] for spec in initial if spec["id"].startswith("D-")]
    daily_ids = [spec["id"] for spec in initial if spec["id"].startswith("L-")]
    base_direct = _winner(study.records, direct_ids, require_admission=False)
    base_daily = _winner(study.records, daily_ids, require_admission=False)
    regime_ids = []
    for base_id in (base_direct, base_daily):
        if base_id is None:
            continue
        base = study.records[base_id]["config"]
        experiment_id = f"R-{base_id}"
        spec = {
            "id": experiment_id,
            "hypothesis": f"Past-only detected regime age improves {base_id}, especially routes 7/17/50.",
            "change": "Only use_detected_regime=True; no external source feature.",
            "config": score_v3_config(base["kind"], experiment_id, **{
                key: value for key, value in base.items()
                if key not in {"schema", "kind", "id", "model_name", "information_mode", "weather_columns", "weather_groups", "alignment", "use_detected_regime"}
            }, use_detected_regime=True),
        }
        study.evaluate(spec)
        regime_ids.append(experiment_id)
        trained += 1

    best_regime = _winner(study.records, regime_ids, require_admission=False)
    if best_regime is not None:
        base = study.records[best_regime]["config"]
        experiment_id = f"S-{best_regime}"
        spec = {
            "id": experiment_id,
            "hypothesis": "The origin-available T01 route 7/50 restriction adds signal beyond detected history.",
            "change": "Only use_source_regimes=True using the frozen, verified T01 publication timeline.",
            "config": score_v3_config(base["kind"], experiment_id, **{
                key: value for key, value in base.items()
                if key not in {"schema", "kind", "id", "model_name", "information_mode", "weather_columns", "weather_groups", "alignment", "use_source_regimes"}
            }, use_source_regimes=True),
        }
        study.evaluate(spec)
        trained += 1

    if trained > config["new_training_config_limit"]:
        raise ValueError("Primary training configuration cap exceeded")

    best_direct = _winner(study.records, direct_ids + [name for name in regime_ids if "D-" in name], require_admission=False)
    best_daily = _winner(study.records, daily_ids + [name for name in regime_ids if "L-" in name], require_admission=False)
    for candidate_id in dict.fromkeys(name for name in (best_direct, best_daily) if name):
        for weight in config["blend_weights"]:
            study.blend(f"E-{candidate_id}-{int(weight * 100):02d}", candidate_id, weight)

    candidate_ids = [name for name in study.records if name not in ("B0", "B1", "B2")]
    selected = _winner(study.records, candidate_ids, require_admission=True)
    selection = {
        "created_before_reused_diagnostic": True,
        "selection_data": "S1-S4 only; 61-day windows; overlapping and not independent",
        "diagnostic_status": "D was used in prior work and is not an independent holdout",
        "selected_id": selected,
        "selected_config": study.records[selected]["config"] if selected else None,
        "decision": "candidate_frozen" if selected else "no_improvement_on_selection_guardrails",
        "new_training_configurations": trained,
        "new_training_config_limit": config["new_training_config_limit"],
    }
    if not (output / "selection.json").exists():
        _write_json(output / "selection.json", selection)
    elif json.loads((output / "selection.json").read_text(encoding="utf-8")) != selection:
        raise ValueError("Frozen selection differs on resume")

    diagnostic_spec = next(spec for spec in _control_specs(common) if spec["id"] == "B2")
    diagnostic_spec = {**diagnostic_spec, "id": "D-B2"}
    diagnostic_spec["config"] = score_v3_config("current_ensemble", "D-B2", **common)
    d_baseline = study.evaluate(diagnostic_spec, [config["diagnostic"]], diagnostic=True)
    d_baseline_summary = summarize_v3(d_baseline)
    if not np.isclose(d_baseline_summary["rounded"]["score"], EXPECTED_CONTROL_SCORES["D"], atol=1e-12, rtol=0):
        raise ValueError("Reused D baseline mismatch")
    d_result = None
    if selected:
        selected_spec = {
            "id": f"D-{selected}",
            "hypothesis": study.records[selected]["hypothesis"],
            "change": study.records[selected]["change"],
            "config": study.records[selected]["config"],
        }
        d_candidate = study.evaluate(selected_spec, [config["diagnostic"]], diagnostic=True)
        assert_same_tasks(d_candidate, d_baseline)
        d_result = {
            "baseline": d_baseline_summary,
            "candidate": summarize_v3(d_candidate),
        }
        d_result["delta_score"] = d_result["candidate"]["rounded"]["score"] - d_result["baseline"]["rounded"]["score"]
        d_result["passed"] = d_result["delta_score"] >= config["thresholds"]["diagnostic_min_delta"]
        d_result["status"] = "reused_diagnostic_not_independent"

    uncertainty = block_uncertainty(study.frames[selected], study.frames["B2"], config["seed"]) if selected else None
    adopted = bool(selected and d_result and d_result["passed"])
    final_outputs = None
    if adopted:
        artifact = output / "final-artifact"
        if not artifact.exists():
            absolute_errors = np.abs(
                study.frames[selected][TARGET_COLUMN].to_numpy(dtype=float)
                - np.floor(study.frames[selected]["prediction"].to_numpy(dtype=float) + 0.5)
            )
            create_artifact(
                dataset,
                artifact,
                model_name=study.records[selected]["config"]["model_name"],
                experiment_config=study.records[selected]["config"],
                interval_absolute_error_q90=float(np.quantile(absolute_errors, 0.9)),
            )
        submission = output / "submission-score-v3.csv"
        if not submission.exists():
            payload = joblib.load(artifact / "model.joblib")
            prediction = payload["model"].predict("2025-11-01", "2025-12-31")
            write_submission(prediction, dataset / "test_submission.csv", submission, scope="sample")
        preflight = submission_preflight(submission, dataset / "test_submission.csv", scope="sample")
        final_outputs = {
            "artifact": str(artifact),
            "submission": str(submission),
            "submission_sha256": sha256_file(submission),
            "preflight": preflight,
        }

    _journal(study.records, output / "experiment-journal.csv")
    result = {
        "schema": "score-v3-result",
        "fingerprint": fingerprint["fingerprint"],
        "selection": selection,
        "controls": {name: study.records[name]["summary"] for name in ("B0", "B1", "B2")},
        "experiments": {name: record for name, record in study.records.items() if name not in ("B0", "B1", "B2")},
        "uncertainty": uncertainty,
        "reused_diagnostic": d_result or {"baseline": d_baseline_summary, "candidate": None, "status": "not_opened_without_eligible_candidate"},
        "decision": "adopted" if adopted else "no_improvement",
        "final_outputs": final_outputs,
        "reported_platform_baseline": 0.83732,
        "platform_score": None,
        "goal_0_90_0_95_status": "target_only_not_demonstrated",
    }
    _write_json(completed, result)
    return result
