"""Isolated route-50 weekend study; immutable outputs, no submission upload.

Run from the repository root with ``python -m scripts.route50_weekends --help``.
Only audited, small organizer labels and saved origin-specific B2 OOF are read.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.artifact import predict_artifact, submission_preflight, write_submission
from ml.data import load_organizer_labels, validate_target_rows
from ml.factors import add_official_calendar_features, sha256_file
from ml.score_improvement import block_uncertainty, digest, guardrail, metrics, write_json
from ml.score_v3_study import EXPECTED_CONTROL_SCORES, _fit_one
from ml.score_v3 import score_v3_config
from ml.settings import KEY_COLUMNS, MODELED_ROUTES


BASELINE_SHA = "505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94"


def calendar(frame):
    result = add_official_calendar_features(frame)
    result["dow"] = result.date.dt.dayofweek
    result["day_type"] = np.select(
        [result.is_working_weekend.eq(1), result.is_public_holiday.eq(1),
         result.is_transferred_day_off.eq(1), result.dow.ge(5)],
        ["working_weekend", "public_holiday", "transferred_day_off", "ordinary_weekend"],
        default="workday",
    )
    return result


def weekend_mask(frame):
    enriched = calendar(frame)
    return enriched.route.eq(50).to_numpy() & enriched.day_type.eq("ordinary_weekend").to_numpy()


def fit_profile(history, origin, window):
    """Freeze weekday/hour arithmetic means over [origin-window, origin).

    Exclude no outliers. Missing count cells must have been expanded by the
    organizer-label loader. Incomplete days fail rather than being imputed.
    """
    if window not in (28, 56):
        raise ValueError("Only the prespecified 28/56-day windows are supported")
    origin = pd.Timestamp(origin)
    recent = history[history.route.eq(50) & history.date.ge(origin - pd.Timedelta(days=window))
                     & history.date.lt(origin)].copy()
    validate_target_rows(recent)
    if not np.isfinite(recent.boardings).all():
        raise ValueError("Nonfinite training target")
    recent = calendar(recent)
    recent = recent[recent.day_type.eq("ordinary_weekend")].copy()
    if recent.empty or not recent.groupby("date").hour.nunique().eq(24).all():
        raise ValueError("Profile needs complete observed weekend days")
    profile = recent.groupby(["dow", "hour"], as_index=False).agg(
        profile=("boardings", "mean"), observations=("date", "nunique")
    )
    if len(profile) != 48 or profile.observations.min() < 3:
        raise ValueError("Profile needs at least three complete Saturdays and Sundays")
    audit = {
        "origin": str(origin.date()), "window_days": window,
        "allowed_start": str((origin - pd.Timedelta(days=window)).date()),
        "exclusive_end": str(origin.date()),
        "dates_used": sorted(recent.date.dt.strftime("%Y-%m-%d").unique().tolist()),
        "days_by_dow": {str(k): int(v) for k, v in recent.groupby("dow").date.nunique().items()},
        "statistic": "arithmetic mean by Saturday/Sunday and hour; no outlier removal",
        "excluded_calendar_days": "workdays, working weekends, public holidays, transferred days off",
    }
    return profile, audit


def apply_profile(base, profile, weight):
    if not 0 < weight <= 1:
        raise ValueError("Profile weight must be in (0,1]")
    if (profile.profile < 0).any() or not np.isfinite(profile.profile).all():
        raise ValueError("Invalid profile")
    result = base.copy()
    mask = weekend_mask(base)
    target = calendar(base.loc[mask, list(KEY_COLUMNS)]).merge(
        profile, on=["dow", "hour"], how="left", validate="many_to_one"
    )
    if target.profile.isna().any():
        raise ValueError("Missing profile cells")
    result.loc[mask, "prediction"] = ((1 - weight) * base.loc[mask, "prediction"].to_numpy()
                                      + weight * target.profile.to_numpy())
    if not result.loc[~mask].equals(base.loc[~mask]):
        raise AssertionError("Rows outside route-50 ordinary weekends changed")
    return result


def measure(frame, rounded=True):
    if frame.empty:
        return {"rows": 0, "score": None, "wape": None, "mae": None}
    result = metrics(frame, rounded)
    result["wape"] = result["absolute_error"] / result["sum_y"] if result["sum_y"] else None
    day_keys = [c for c in ("fold", "route", "date") if c in frame]
    days = len(frame[day_keys].drop_duplicates())
    result["mean_daily_actual"] = float(frame.boardings.sum() / days)
    prediction = np.floor(frame.prediction + .5) if rounded else frame.prediction
    result["mean_daily_prediction"] = float(prediction.sum() / days)
    return result


def summarize(frame):
    data = calendar(frame)
    route = data[data.route.eq(50)]
    weekend = route[route.day_type.eq("ordinary_weekend")]
    return {
        "rounded": measure(data), "raw": measure(data, False),
        "route50_weekends": measure(weekend),
        "route50_day_types": {name: measure(part) for name, part in route.groupby("day_type")},
        "route50_weekend_hours": {str(h): measure(part) for h, part in weekend.groupby("hour")},
    }


def load_control(run, fold, labels):
    path = run / "folds" / ("D-B2" if fold["id"] == "D" else "B2") / fold["id"]
    record = json.loads((path / "record.json").read_text())
    if (record["fold"] != fold or record["config"]["kind"] != "current_ensemble"
            or record["fit"]["model"]["train_end"] != fold["train_end"]
            or pd.Timestamp(fold["train_end"]) + pd.Timedelta(days=1) != pd.Timestamp(fold["start"])):
        raise ValueError("Control origin/config mismatch")
    if sha256_file(path / "oof.csv") != record["oof_sha256"]:
        raise ValueError("Control checksum mismatch")
    frame = pd.read_csv(path / "oof.csv", parse_dates=["date"], float_precision="round_trip")
    expected = labels[labels.date.between(fold["start"], fold["end"]) & labels.route.isin(MODELED_ROUTES)]
    columns = [*KEY_COLUMNS, "boardings"]
    pd.testing.assert_frame_equal(
        frame[columns].sort_values(list(KEY_COLUMNS)).reset_index(drop=True),
        expected[columns].sort_values(list(KEY_COLUMNS)).reset_index(drop=True),
    )
    if not frame.fold.eq(fold["id"]).all() or not frame.horizon_day.eq(
        (frame.date - pd.Timestamp(fold["start"])).dt.days + 1
    ).all():
        raise ValueError("Invalid forecast task horizons")
    if abs(metrics(frame)["score"] - EXPECTED_CONTROL_SCORES[fold["id"]]) > 1e-12:
        raise ValueError("Control score mismatch")
    return frame, record


def run(args):
    dataset, control, output = args.dataset_dir, args.control_run, args.output_dir
    if output.exists():
        raise ValueError("Output exists; select a new run directory")
    old_fingerprint = json.loads((control / "fingerprint.json").read_text())
    data_hashes = {name: sha256_file(dataset / name) for name in old_fingerprint["data"]}
    if data_hashes != old_fingerprint["data"]:
        raise ValueError("Audited control data differ from current labels/sample")
    if sha256_file(args.baseline_submission) != BASELINE_SHA:
        raise ValueError("Not the identified incumbent submission")
    base_preflight = submission_preflight(args.baseline_submission, dataset / "test_submission.csv")
    if not base_preflight["passed"]:
        raise ValueError("Incumbent preflight failed")
    protocol = json.loads((control / "config.json").read_text())
    specs = [{"id": f"R{window // 7}-{int(weight * 100)}", "window": window, "weight": weight}
             for window in (28, 56) for weight in (.25, .5, .75, 1.)]
    config = {
        "schema": "route50-weekend-study-v1", "folds": protocol["folds"],
        "diagnostic": protocol["diagnostic"], "thresholds": protocol["thresholds"],
        "candidates": specs, "selection": "highest rounded score among original v3 guardrail passers",
        "diagnostic_rule": "freeze selection before D; report entire fixed grid descriptively; require nonnegative D delta of selected; no replacement search",
        "recent_regime_diagnostic": {"id": "C", "train_start": "2025-01-01", "train_end": "2025-09-30",
                                     "start": "2025-10-01", "end": "2025-10-31",
                                     "use": "31 days only, descriptive check after September break; never selection/admission"},
        "holidays": "evaluate separately; retain incumbent on holidays, transferred days and working Saturday",
        "reported_incumbent_platform_score": .84260, "platform_score_evidence": "user report, not independently verified",
        "warning": "S1-S4 overlap and were inspected; D reused and motivated this hypothesis; no independent holdout",
    }
    sources = [*Path("ml").glob("*.py"), Path(__file__), Path("tests/ml/test_route50_weekends.py")]
    fingerprint = {"config": config, "data": data_hashes, "baseline_sha256": BASELINE_SHA,
                   "control_run_fingerprint": old_fingerprint["fingerprint"],
                   "sources": {str(p): sha256_file(p) for p in sources},
                   "dependencies": {p: importlib.metadata.version(p) for p in ("pandas", "numpy", "scikit-learn", "joblib")}}
    fingerprint["fingerprint"] = digest(fingerprint)
    output.mkdir(parents=True)
    write_json(output / "config.json", config)
    write_json(output / "fingerprint.json", fingerprint)
    labels = load_organizer_labels(dataset, "2025-01-01", "2025-10-31")
    # Reproduce incumbent with floats: blending integer CSV would double-round.
    with threadpool_limits(limits=4):
        final_base = predict_artifact(args.baseline_artifact, "2025-11-01", "2025-12-31")
    reproduced = output / "incumbent-reproduced.csv"
    write_submission(final_base, dataset / "test_submission.csv", reproduced)
    if sha256_file(reproduced) != BASELINE_SHA:
        raise ValueError("Incumbent artifact does not reproduce CSV byte-for-byte")
    parts = {"B2": []} | {s["id"]: [] for s in specs}
    provenance = {}
    for fold in protocol["folds"]:
        base, record = load_control(control, fold, labels)
        provenance[fold["id"]] = record
        parts["B2"].append(base)
        for window in (28, 56):
            profile, audit = fit_profile(labels, fold["start"], window)
            destination = output / "profiles" / fold["id"]
            destination.mkdir(parents=True, exist_ok=True)
            profile.to_csv(destination / f"{window}.csv", index=False)
            write_json(destination / f"{window}.json", audit)
            for spec in (s for s in specs if s["window"] == window):
                parts[spec["id"]].append(apply_profile(base, profile, spec["weight"]))
    frames = {name: pd.concat(items, ignore_index=True) for name, items in parts.items()}
    results, journal, fold_rows = {}, [], []
    for name, frame in frames.items():
        summary = summarize(frame)
        admission = guardrail(frame, frames["B2"], config["thresholds"]) if name != "B2" else None
        result = {"summary": summary, "admission": admission,
                  "folds": {f: summarize(part) for f, part in frame.groupby("fold")}}
        results[name] = result
        destination = output / "experiments" / name
        destination.mkdir(parents=True)
        frame.to_csv(destination / "oof.csv", index=False)
        result["oof_sha256"] = sha256_file(destination / "oof.csv")
        write_json(destination / "record.json", result)
        journal.append({"id": name, "hypothesis": "recent route50 weekend weekday/hour mean persists for 61 days",
                        "change": next((s for s in specs if s["id"] == name), "unchanged B2"),
                        "score": summary["rounded"]["score"], "weekend_wape": summary["route50_weekends"]["wape"],
                        "decision": "control" if admission is None else ("eligible" if admission["passed"] else "rejected"),
                        "admission": admission, "slices": str(destination / "record.json")})
        for f, values in result["folds"].items():
            fold_rows.append({"id": name, "fold": f, "score": values["rounded"]["score"],
                              "delta": values["rounded"]["score"] - results["B2"]["folds"][f]["rounded"]["score"],
                              **{f"weekend_{k}": v for k, v in values["route50_weekends"].items()}})
        print(json.dumps({"id": name, "score": summary["rounded"]["score"], "admission": admission}), flush=True)
    pd.DataFrame(journal).to_csv(output / "experiment-journal.csv", index=False)
    pd.DataFrame(fold_rows).to_csv(output / "fold-comparison.csv", index=False)
    eligible = [s for s in specs if results[s["id"]]["admission"]["passed"]]
    selected = max(eligible, key=lambda s: results[s["id"]]["summary"]["rounded"]["score"]) if eligible else None
    best = max(specs, key=lambda s: results[s["id"]]["summary"]["rounded"]["score"])
    selection = {"selected": selected, "best_by_score": best, "results": results, "warning": config["warning"],
                 "best_by_score_bootstrap": block_uncertainty(frames[best["id"]], frames["B2"], 20250925)}
    write_json(output / "selection.json", selection)
    # All fixed variants are shown on reused D, but none can be selected by D.
    base_d, record = load_control(control, protocol["diagnostic"], labels)
    provenance["D"] = record
    diagnostic = {"baseline": summarize(base_d), "selection_sha256": sha256_file(output / "selection.json"),
                  "warning": config["warning"], "selected": None, "candidates": {}}
    recommended = False
    for window in (28, 56):
        profile, audit = fit_profile(labels, protocol["diagnostic"]["start"], window)
        destination = output / "profiles" / "D"
        destination.mkdir(parents=True, exist_ok=True)
        profile.to_csv(destination / f"{window}.csv", index=False)
        write_json(destination / f"{window}.json", audit)
        for spec in (s for s in specs if s["window"] == window):
            candidate_d = apply_profile(base_d, profile, spec["weight"])
            summary = summarize(candidate_d)
            delta = metrics(candidate_d)["score"] - metrics(base_d)["score"]
            diagnostic["candidates"][spec["id"]] = {"summary": summary, "delta": delta}
            candidate_d.to_csv(output / f"diagnostic-{spec['id']}-oof.csv", index=False)
            if selected and spec["id"] == selected["id"]:
                diagnostic["selected"] = summary
                diagnostic["delta"] = delta
                recommended = delta >= 0
    write_json(output / "diagnostic.json", diagnostic)
    write_json(output / "control-provenance.json", provenance)
    # A September-origin forecast could not observe the break. This separate
    # October-origin check measures persistence once September is actually past.
    # It has only 31 observed days, not a new 61-day admission window.
    recent_fold = {k: v for k, v in config["recent_regime_diagnostic"].items() if k != "use"}
    _, recent_base, fit_details = _fit_one(labels[labels.route.isin(MODELED_ROUTES)],
        score_v3_config("current_ensemble", "B2"), recent_fold, threads=4)
    recent_result = {"fold": recent_fold, "fit": fit_details, "baseline": summarize(recent_base),
                     "candidates": {}, "used_for_selection_or_admission": False}
    recent_base.to_csv(output / "recent-C-B2-oof.csv", index=False)
    for window in (28, 56):
        profile, audit = fit_profile(labels, recent_fold["start"], window)
        destination = output / "profiles" / "C"
        destination.mkdir(parents=True, exist_ok=True)
        profile.to_csv(destination / f"{window}.csv", index=False)
        write_json(destination / f"{window}.json", audit)
        for spec in (s for s in specs if s["window"] == window):
            candidate = apply_profile(recent_base, profile, spec["weight"])
            recent_result["candidates"][spec["id"]] = {
                "summary": summarize(candidate),
                "delta": metrics(candidate)["score"] - metrics(recent_base)["score"],
            }
            candidate.to_csv(output / f"recent-C-{spec['id']}-oof.csv", index=False)
    write_json(output / "recent-regime-diagnostic.json", recent_result)
    # Descriptive final profiles and calendar audit do not participate in selection.
    final_profiles = {}
    for window in (28, 56):
        profile, audit = fit_profile(labels, "2025-11-01", window)
        profile.to_csv(output / f"final-profile-{window}.csv", index=False)
        write_json(output / f"final-profile-{window}.json", audit)
        final_profiles[window] = profile
    daily = calendar(labels[labels.route.eq(50)]).groupby(["date", "day_type"], as_index=False).boardings.sum()
    daily.to_csv(output / "route50-history-daily.csv", index=False)
    final_candidates = {"B2": final_base} | {
        s["id"]: apply_profile(final_base, final_profiles[s["window"]], s["weight"]) for s in specs}
    daily_forecasts, hourly = [], []
    for name, frame in final_candidates.items():
        enriched = calendar(frame[frame.route.eq(50)])
        enriched["prediction"] = np.floor(enriched.prediction + .5).astype("int64")
        daily_forecasts.append(enriched.groupby(["date", "day_type"], as_index=False).prediction.sum().assign(id=name))
        hourly.append(enriched[enriched.day_type.eq("ordinary_weekend")].groupby(
            ["dow", "hour"], as_index=False).prediction.mean().assign(id=name))
    pd.concat(daily_forecasts).to_csv(output / "final-daily-comparison.csv", index=False)
    pd.concat(hourly).to_csv(output / "final-hourly-comparison.csv", index=False)
    complete = {"recommended": recommended, "selected": selected, "platform_score": None}
    if recommended:
        submission = output / "submission-route50-weekends.csv"
        write_submission(final_candidates[selected["id"]], dataset / "test_submission.csv", submission)
        check = submission_preflight(submission, dataset / "test_submission.csv")
        before = pd.read_csv(args.baseline_submission, sep=";")
        after = pd.read_csv(submission, sep=";")
        permitted = weekend_mask(before)
        check["isolation"] = {
            "other_rows_identical": bool(before.loc[~permitted].equals(after.loc[~permitted])),
            "changed_rows": int(before.prediction.ne(after.prediction).sum()),
            "allowed_rows": int(permitted.sum()),
            "route5_zero_rows": int((after.route.eq(5) & after.prediction.eq(0)).sum()),
            "baseline_sha256": BASELINE_SHA,
        }
        if not check["passed"] or not check["isolation"]["other_rows_identical"]:
            raise ValueError("Final preflight/isolation failed")
        write_json(output / "submission-route50-weekends.preflight.json", check)
        (output / "submission-route50-weekends.csv.sha256").write_text(
            f"{check['sha256']}  {submission.name}\n", encoding="utf-8")
        complete.update(submission=str(submission), sha256=check["sha256"])
    write_json(output / "complete.json", complete)
    print(json.dumps(complete), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--control-run", type=Path, default=Path("artifacts/score-v3-20260926-r02"))
    parser.add_argument("--baseline-artifact", type=Path, default=Path("artifacts/quality-085/calendar-interaction-ensemble"))
    parser.add_argument("--baseline-submission", type=Path, default=Path("artifacts/quality-085/submission-calendar-interaction-ensemble-10-routes.csv"))
    parser.add_argument("--output-dir", type=Path, required=True)
    run(parser.parse_args())
