"""A single preregistered history-only gate for route-50 weekend profiles."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.artifact import predict_artifact, submission_preflight, write_submission
from ml.data import full_hourly_grid, load_organizer_labels, validate_target_rows
from ml.factors import sha256_file
from ml.score_improvement import digest, write_json
from ml.score_v3 import score_v3_config
from ml.score_v3_study import _fit_one
from ml.settings import KEY_COLUMNS, MODELED_ROUTES
from scripts.route50_weekends import (
    BASELINE_SHA, apply_profile, calendar, fit_profile, load_control, summarize,
    weekend_mask,
)


def switch_decision(history, origin, config):
    """No date-specific thresholds, future rows or forecast targets enter here."""
    origin = pd.Timestamp(origin).normalize()
    split = origin - pd.Timedelta(days=config["profile_days"])
    start = split - pd.Timedelta(days=config["reference_days"])
    past = history[history.route.eq(50) & history.date.ge(start) & history.date.lt(origin)].copy()
    audit = {"origin": origin.strftime("%Y-%m-%d"), "enabled": False,
             "reference_start": str(start.date()), "reference_end_exclusive": str(split.date()),
             "profile_start": str(split.date()), "profile_end_exclusive": str(origin.date()),
             "maximum_level_ratio": config["maximum_level_ratio"], "reason": "insufficient_history"}
    if past.empty:
        return audit
    validate_target_rows(past)
    if not np.isfinite(past.boardings).all():
        raise ValueError("Nonfinite historical target")
    expected = full_hourly_grid(max(start, past.date.min()), origin - pd.Timedelta(days=1), routes=(50,))
    keys = list(KEY_COLUMNS)
    if not past[keys].sort_values(keys).reset_index(drop=True).equals(expected.sort_values(keys).reset_index(drop=True)):
        raise ValueError("Incomplete historical hourly grid; missing data cannot stand for a decline")
    daily = calendar(past).groupby(["date", "dow", "day_type"], as_index=False).boardings.sum()
    ordinary = daily[daily.day_type.eq("ordinary_weekend")]
    reference = ordinary[ordinary.date.lt(split)]
    recent = ordinary[ordinary.date.ge(split)]
    audit["reference_dates"] = reference.date.dt.strftime("%Y-%m-%d").tolist()
    audit["recent_dates"] = recent.date.dt.strftime("%Y-%m-%d").tolist()
    ref_counts = reference.groupby("dow").size().reindex([5, 6], fill_value=0)
    new_counts = recent.groupby("dow").size().reindex([5, 6], fill_value=0)
    if (ref_counts.min() < config["minimum_reference_days_per_dow"]
            or new_counts.min() < config["minimum_recent_days_per_dow"]):
        return audit
    medians = reference.groupby("dow").boardings.median()
    means = recent.groupby("dow").boardings.mean()
    audit["reference_medians"] = {str(k): float(v) for k, v in medians.items()}
    audit["recent_means"] = {str(k): float(v) for k, v in means.items()}
    if medians.le(0).any():
        audit["reason"] = "nonpositive_reference"
        return audit
    ratios = means / medians
    audit["recent_ratios"] = {str(k): float(v) for k, v in ratios.items()}
    ordinary_dates = set(recent.date)
    saturdays = sorted(d for d in ordinary_dates if d.dayofweek == 5 and d + pd.Timedelta(days=1) in ordinary_dates)
    saturdays = saturdays[-config["consecutive_weekends"]:]
    if (len(saturdays) != config["consecutive_weekends"]
            or any(b - a != pd.Timedelta(days=7) for a, b in zip(saturdays, saturdays[1:]))):
        audit["reason"] = "not_enough_consecutive_complete_weekends"
        return audit
    dates = [day + pd.Timedelta(days=offset) for day in saturdays for offset in (0, 1)]
    last = recent[recent.date.isin(dates)].sort_values("date").copy()
    last["ratio"] = last.boardings / last.dow.map(medians)
    audit["last_complete_weekends"] = [
        {"date": str(row.date.date()), "boardings": int(row.boardings), "ratio": float(row.ratio)}
        for row in last.itertuples()
    ]
    audit["enabled"] = bool(ratios.le(config["maximum_level_ratio"]).all()
                            and last.ratio.le(config["maximum_level_ratio"]).all())
    audit["reason"] = "sustained_decline" if audit["enabled"] else "decline_not_confirmed"
    return audit


def correct(base, history, origin, config):
    if base.date.min() < pd.Timestamp(origin):
        raise ValueError("Forecast starts before origin")
    decision = switch_decision(history, origin, config)
    if not decision["enabled"]:
        return base.copy(), decision, None
    profile, audit = fit_profile(history, origin, config["profile_days"])
    decision["profile_audit"] = audit
    return apply_profile(base, profile, config["profile_weight"]), decision, profile


def comparison(base, candidate):
    baseline, adaptive = summarize(base), summarize(candidate)
    b, a = baseline["route50_weekends"], adaptive["route50_weekends"]
    return {"baseline": baseline, "adaptive": adaptive,
            "delta_score": adaptive["rounded"]["score"] - baseline["rounded"]["score"],
            "weekend_sae_reduction": 1 - a["absolute_error"] / b["absolute_error"] if b["absolute_error"] else 0.}


def research_admission(records, final_decision, config):
    rules = config["research_export_criteria"]
    old = [r for r in records.values() if r["kind"] == "previous"]
    new = [r for r in records.values() if r["kind"] == "additional"]
    primary = next(r for r in new if r["origin"] == config["primary_origin"])["october"]
    checks = {
        "old_windows_noninferior": all(r["full"]["delta_score"] >= rules["minimum_old_window_delta"] for r in old),
        "additional_windows_noninferior": all(
            r[scope]["delta_score"] >= rules["minimum_additional_window_delta"]
            for r in new for scope in ("full", "october")),
        "primary_gain_positive": primary["delta_score"] > 0,
        "primary_weekend_sae_reduced": primary["weekend_sae_reduction"] >= rules["primary_weekend_sae_reduction_at_least"],
        "final_origin_switches": final_decision["enabled"],
    }
    return {"research_export_allowed": all(checks.values()), "checks": checks,
            "primary_origin": config["primary_origin"], "independent_low_regime_periods": 1,
            "incumbent_replacement": False}


def export_research(candidate, baseline_submission, template, output, decision):
    submission = output / "submission-route50-adaptive-research.csv"
    write_submission(candidate, template, submission)
    before = pd.read_csv(baseline_submission, sep=";")
    after = pd.read_csv(submission, sep=";")
    allowed = weekend_mask(before)
    preflight = submission_preflight(submission, template)
    checks = {
        "other_rows_identical": bool(before.loc[~allowed].equals(after.loc[~allowed])),
        "changed_rows": int(before.prediction.ne(after.prediction).sum()),
        "allowed_rows": int(allowed.sum()),
        "rows": len(after), "route5_zero_rows": int((after.route.eq(5) & after.prediction.eq(0)).sum()),
        "baseline_sha256": sha256_file(baseline_submission),
    }
    if not preflight["passed"] or not checks["other_rows_identical"] or checks["rows"] != 14640 or checks["route5_zero_rows"] != 1464:
        raise ValueError("Research submission isolation/preflight failed")
    preflight.update(isolation=checks, status="research_only_not_incumbent", switch_decision=decision)
    write_json(output / "submission-route50-adaptive-research.preflight.json", preflight)
    (output / "submission-route50-adaptive-research.csv.sha256").write_text(
        f"{preflight['sha256']}  {submission.name}\n", encoding="utf-8")
    return {"path": str(submission), "sha256": preflight["sha256"], "isolation": checks}


def run(args):
    if args.output_dir.exists():
        raise ValueError("Choose a new output directory; completed runs are immutable")
    config = json.loads(args.config.read_text())
    if config["schema"] != "route50-adaptive-v1" or config["profile_days"] != 28:
        raise ValueError("Unknown adaptive protocol")
    control_fingerprint = json.loads((args.control_run / "fingerprint.json").read_text())
    data_hashes = {name: sha256_file(args.dataset_dir / name) for name in control_fingerprint["data"]}
    if data_hashes != control_fingerprint["data"] or sha256_file(args.baseline_submission) != BASELINE_SHA:
        raise ValueError("Inputs differ from audited labels/sample/incumbent")
    source_paths = [*sorted(Path("ml").glob("*.py")), Path(__file__), Path("scripts/route50_weekends.py"),
                    Path("tests/ml/test_route50_adaptive.py"), args.config,
                    Path("ml/reports/route50-adaptive-protocol-2026-09-26.md")]
    fingerprint = {"config": config, "data": data_hashes,
                   "sources": {str(p): sha256_file(p) for p in source_paths},
                   "dependencies": {p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scikit-learn", "joblib")},
                   "control_fingerprint": control_fingerprint["fingerprint"], "baseline_sha256": BASELINE_SHA}
    fingerprint["fingerprint"] = digest(fingerprint)
    output = args.output_dir
    output.mkdir(parents=True)
    write_json(output / "protocol.json", config)
    write_json(output / "fingerprint.json", fingerprint)
    # Only now load target; protocol and exact implementation have been frozen.
    history = load_organizer_labels(args.dataset_dir, "2025-01-01", config["last_observed_date"])
    protocol = json.loads((args.control_run / "config.json").read_text())
    folds = [{**f, "kind": "previous", "cached": True} for f in [*protocol["folds"], protocol["diagnostic"]]]
    folds.append({"id": "C", "train_start": "2025-01-01", "train_end": "2025-09-30",
                  "start": "2025-10-01", "end": "2025-10-31", "kind": "previous", "cached": False})
    for origin in config["additional_origins"]:
        start = pd.Timestamp(origin)
        end = min(start + pd.Timedelta(days=60), pd.Timestamp(config["last_observed_date"]))
        folds.append({"id": "A-" + origin, "train_start": "2025-01-01",
                      "train_end": str((start - pd.Timedelta(days=1)).date()),
                      "start": origin, "end": str(end.date()), "kind": "additional", "cached": False})
    records, rows, old_frames = {}, [], []
    for entry in folds:
        fold = {k: v for k, v in entry.items() if k not in ("kind", "cached")}
        target = output / "folds" / fold["id"]
        target.mkdir(parents=True)
        if entry["cached"]:
            base, provenance = load_control(args.control_run, fold, history)
        else:
            model, base, fit = _fit_one(history[history.route.isin(MODELED_ROUTES)],
                                       score_v3_config("current_ensemble", "B2"), fold, threads=4)
            joblib.dump(model, target / "baseline-model.joblib", compress=3)
            provenance = {"fit": fit, "fold": fold, "model_sha256": sha256_file(target / "baseline-model.joblib")}
        candidate, decision, profile = correct(base, history, fold["start"], config)
        full = comparison(base, candidate)
        record = {"origin": fold["start"], "kind": entry["kind"], "fold": fold,
                  "observed_horizon_days": int(base.horizon_day.max()), "decision": decision,
                  "full": full, "provenance": provenance}
        scopes = {"full": full}
        if entry["kind"] == "additional":
            scope = base.date.ge(config["common_evaluation_start"])
            record["october"] = comparison(base[scope], candidate[scope])
            scopes["october"] = record["october"]
        if fold["id"].startswith("S"):
            old_frames.append((base, candidate))
        for name, frame in (("baseline", base), ("adaptive", candidate)):
            frame.to_csv(target / f"{name}.csv", index=False)
            record[f"{name}_sha256"] = sha256_file(target / f"{name}.csv")
        if profile is not None:
            profile.to_csv(target / "profile.csv", index=False)
        write_json(target / "record.json", record)
        records[fold["id"]] = record
        for scope, values in scopes.items():
            rows.append({"fold": fold["id"], "scope": scope, "origin": fold["start"],
                         "switched": decision["enabled"], "reason": decision["reason"],
                         "baseline_score": values["baseline"]["rounded"]["score"],
                         "adaptive_score": values["adaptive"]["rounded"]["score"],
                         "delta_score": values["delta_score"],
                         "baseline_weekend_mae": values["baseline"]["route50_weekends"]["mae"],
                         "adaptive_weekend_mae": values["adaptive"]["route50_weekends"]["mae"],
                         "baseline_weekend_wape": values["baseline"]["route50_weekends"]["wape"],
                         "adaptive_weekend_wape": values["adaptive"]["route50_weekends"]["wape"],
                         "weekend_sae_reduction": values["weekend_sae_reduction"]})
        print(json.dumps(rows[-1]), flush=True)
    pd.DataFrame(rows).to_csv(output / "window-comparison.csv", index=False)
    combined = comparison(pd.concat([f[0] for f in old_frames]), pd.concat([f[1] for f in old_frames]))
    # Daily scan is descriptive: it cannot select evaluation origins or thresholds.
    scan = [switch_decision(history, d, config) for d in pd.date_range("2025-01-01", "2025-11-01")]
    transitions = [row for i, row in enumerate(scan) if row["enabled"] != (scan[i-1]["enabled"] if i else False)]
    write_json(output / "daily-decisions.json", scan)
    pd.DataFrame([{"origin": r["origin"], "enabled": r["enabled"], "reason": r["reason"],
                   "saturday_ratio": r.get("recent_ratios", {}).get("5"),
                   "sunday_ratio": r.get("recent_ratios", {}).get("6")} for r in scan]).to_csv(output / "daily-decisions.csv", index=False)
    write_json(output / "switch-transitions.json", transitions)
    final_decision = switch_decision(history, "2025-11-01", config)
    admission = research_admission(records, final_decision, config)
    write_json(output / "research-decision.json", admission)
    result = {"config_sha256": sha256_file(args.config), "combined_S1_S4": combined,
              "switch_transitions": transitions, "final_switch": final_decision,
              "admission": admission, "windows": records, "platform_score": None}
    with threadpool_limits(limits=4):
        final_base = predict_artifact(args.baseline_artifact, "2025-11-01", "2025-12-31")
    reproduced = output / "incumbent-reproduced.csv"
    write_submission(final_base, args.dataset_dir / "test_submission.csv", reproduced)
    if sha256_file(reproduced) != BASELINE_SHA:
        raise ValueError("Original artifact does not reproduce incumbent CSV")
    write_json(output / "incumbent.preflight.json", submission_preflight(reproduced, args.dataset_dir / "test_submission.csv"))
    final, decision, profile = correct(final_base, history, "2025-11-01", config)
    if profile is not None:
        profile.to_csv(output / "final-profile.csv", index=False)
    if admission["research_export_allowed"]:
        result["research_submission"] = export_research(final, args.baseline_submission,
            args.dataset_dir / "test_submission.csv", output, decision)
    # Verify inputs remain exactly unchanged, including the primary CSV.
    if sha256_file(args.baseline_submission) != BASELINE_SHA or any(
        sha256_file(args.dataset_dir / name) != checksum for name, checksum in data_hashes.items()
    ):
        raise ValueError("Source data/incumbent changed during the study")
    for title, frame in (("baseline", final_base), ("adaptive", final)):
        part = calendar(frame[frame.route.eq(50)]).copy()
        part.prediction = np.floor(part.prediction + .5).astype("int64")
        part.groupby(["date", "day_type"], as_index=False).prediction.sum().to_csv(output / f"final-{title}-daily.csv", index=False)
    write_json(output / "complete.json", result)
    pd.DataFrame([{"hypothesis": "R4 profile only after persistent history-only decline", "config_sha256": sha256_file(args.config),
                   "S_score": combined["adaptive"]["rounded"]["score"],
                   "decision": "research_export" if admission["research_export_allowed"] else "no_export",
                   "window_slices": "window-comparison.csv", "record": "complete.json",
                   "independent_low_regime_periods": 1, "platform_score": None}]).to_csv(output / "experiment-journal.csv", index=False)
    print(json.dumps({"admission": admission, "submission": result.get("research_submission"),
                      "switch_dates": [r["origin"] for r in transitions]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("ml/experiments/route50-adaptive.json"))
    parser.add_argument("--control-run", type=Path, default=Path("artifacts/score-v3-20260926-r02"))
    parser.add_argument("--baseline-artifact", type=Path, default=Path("artifacts/quality-085/calendar-interaction-ensemble"))
    parser.add_argument("--baseline-submission", type=Path, default=Path("artifacts/quality-085/submission-calendar-interaction-ensemble-10-routes.csv"))
    run(parser.parse_args())
