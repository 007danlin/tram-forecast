"""Consolidate the bounded score-v4 study without opening diagnostic folds.

This step is deliberately evaluation-only: it reads the ten preregistered
S1--S4 OOF forecasts, evaluates at most two fixed-weight blends, and records
whether any candidate is allowed to advance to stress/D evaluation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.score_improvement import assert_same_tasks, guardrail
from ml.score_v3_study import unique_date_diagnostic
from ml.score_v4_metrics import summarize_v4
from ml.score_v4 import sha256_file
from ml.score_v4_study import EXPECTED_B2_OOF_SHA256
from ml.settings import TARGET_COLUMN


OOF_PATHS = {
    "A1": "experiments/A1/oof.csv",
    "A2": "experiments/A2/oof.csv",
    "B1": "experiments/B1/oof.csv",
    "B2-cal": "experiments/B2-cal/oof.csv",
    "C1": "stats-full/C1-oof.csv",
    "C2": "stats-full/C2-oof.csv",
    "N1": "chronos-full/N1-oof.csv",
    "N2": "chronos-full/N2-oof.csv",
    "D1": "direct-full/D1-oof.csv",
    "D2": "direct-full/D2-oof.csv",
    "R1": "reserve/R1-oof.csv",
    "R2": "reserve/R2-oof.csv",
}

# Chosen after the standalone S1--S4 comparison, as allowed by the spec:
# B2-cal is the best new standalone model; C1 is the best standalone model
# outside the incumbent HGBT/calibration family and has materially different
# residuals.  No other candidate or learned weight is examined here.
BLEND_CANDIDATES = ("B2-cal", "C1")
HYPOTHESES = {
    "A1": "Hierarchical L1 multiplier with shrinkage to 1, fitted on honest B2 OOF",
    "A2": "Compact hourly MAE residual over B2 with honest B0/B1 component predictions",
    "B1": "Only remove categorical month/week; keep B2 settings/stopping/weights",
    "B2-cal": "Only add official day-type interactions and fixed weekday transfer rule",
    "C1": "Damped weekly AutoETS on 216 daily route-hour series",
    "C2": "Damped weekly AutoETS on nine daily totals with same-origin B2 shape",
    "N1": "Chronos-2 zero-shot on route groups of 24 daily hour targets",
    "N2": "Chronos-2 zero-shot on nine daily totals with same-origin B2 shape",
    "D1": "V3 direct MAE with origin step 14 -> 5 only",
    "D2": "D1 plus grid-only equal horizon mass after inverse duplicate weighting",
    "R1": "B2-cal calendar component + exact incumbent interaction; unchanged weights/scale",
    "R2": "R1 on official public/transferred holidays, exact B2 on all other dates",
}


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"], float_precision="round_trip")


def _blend(baseline: pd.DataFrame, candidate: pd.DataFrame, weight: float) -> pd.DataFrame:
    result = baseline.copy()
    result["prediction"] = (
        (1.0 - weight) * baseline.prediction.to_numpy(dtype=float)
        + weight * candidate.prediction.to_numpy(dtype=float)
    )
    result["status"] = f"fixed_blend_new_{weight:g}"
    return result


def _record(frame: pd.DataFrame, baseline: pd.DataFrame, thresholds: dict) -> dict:
    admission = guardrail(frame, baseline, thresholds)
    return {
        "summary": summarize_v4(frame),
        "unique_date_diagnostic": unique_date_diagnostic(frame),
        "admission": admission,
        "decision": "eligible" if admission["passed"] else "rejected",
    }


def run(study_root: Path, baseline_root: Path, config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    thresholds = config["thresholds"]
    baseline_path = baseline_root / "experiments" / "B2" / "oof.csv"
    if sha256_file(baseline_path) != EXPECTED_B2_OOF_SHA256:
        raise ValueError("Exact B2 OOF checksum mismatch")
    baseline = _read(baseline_path)

    frames: dict[str, pd.DataFrame] = {}
    records: dict[str, dict] = {}
    baseline_summary = summarize_v4(baseline)
    baseline_residual = (
        baseline[TARGET_COLUMN].to_numpy(dtype=float)
        - baseline.prediction.to_numpy(dtype=float)
    )
    for experiment_id, relative in OOF_PATHS.items():
        path = study_root / relative
        if experiment_id in ("A1", "A2", "B1", "B2-cal"):
            repaired = study_root / "protocol-repair" / relative
            if repaired.exists():
                path = repaired
        frame = _read(path)
        assert_same_tasks(frame, baseline)
        frames[experiment_id] = frame
        record = _record(frame, baseline, thresholds)
        residual = frame[TARGET_COLUMN].to_numpy(dtype=float) - frame.prediction.to_numpy(dtype=float)
        record.update({
            "id": experiment_id,
            "hypothesis": HYPOTHESES[experiment_id],
            "oof_path": str(path),
            "oof_sha256": sha256_file(path),
            "residual_correlation_with_B2": float(np.corrcoef(baseline_residual, residual)[0, 1]),
            "platform_score": None,
        })
        records[experiment_id] = record

    blend_records: dict[str, dict] = {}
    blend_dir = study_root / "blends"
    blend_dir.mkdir(exist_ok=True)
    for candidate_id in BLEND_CANDIDATES:
        for weight in config["blend_weights"]:
            blend_id = f"B2+{weight:g}-{candidate_id}"
            frame = _blend(baseline, frames[candidate_id], float(weight))
            path = blend_dir / f"{blend_id}.csv"
            frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
            record = _record(frame, baseline, thresholds)
            record.update({
                "id": blend_id,
                "hypothesis": f"Fixed float blend: weight {weight:g} of {candidate_id}, remainder B2",
                "new_component": candidate_id,
                "new_component_weight": float(weight),
                "rounding": "only after blending: floor(max(prediction, 0) + 0.5)",
                "oof_path": str(path),
                "oof_sha256": sha256_file(path),
                "platform_score": None,
            })
            blend_records[blend_id] = record

    eligible = [
        record for record in [*records.values(), *blend_records.values()]
        if record["admission"]["passed"]
    ]
    best_new = max(
        [*records.values(), *blend_records.values()],
        key=lambda record: record["summary"]["rounded"]["score"],
    )

    journal_rows = [{
        "id": "B2",
        "hypothesis": "Exact incumbent; original OOF checked by SHA-256",
        "family": "incumbent",
        "score": baseline_summary["rounded"]["score"],
        "delta_to_B2": 0.0,
        "sae": baseline_summary["rounded"]["absolute_error"],
        "bias": baseline_summary["rounded"]["signed_bias"],
        "improved_folds": None,
        "decision": "champion_control",
        "reasons": "",
        "platform_score": 0.84260,
    }]
    for family, collection in (("standalone", records), ("fixed_blend", blend_records)):
        for experiment_id, record in collection.items():
            admission = record["admission"]
            summary = record["summary"]["rounded"]
            journal_rows.append({
                "id": experiment_id,
                "hypothesis": record["hypothesis"],
                "family": family,
                "score": summary["score"],
                "delta_to_B2": admission["delta_score"],
                "sae": summary["absolute_error"],
                "bias": summary["signed_bias"],
                "improved_folds": sum(delta > 0 for delta in admission["fold_deltas"].values()),
                "decision": record["decision"],
                "reasons": "|".join(admission["reasons"]),
                "platform_score": None,
            })
    journal = pd.DataFrame(journal_rows).sort_values(["score", "id"], ascending=[False, True])
    journal.to_csv(study_root / "full-experiment-journal.csv", index=False, encoding="utf-8", lineterminator="\n")
    slice_rows = []
    for experiment_id, summary in [("B2", baseline_summary), *[(key, value["summary"]) for key, value in {**records, **blend_records}.items()]]:
        for slice_name, groups in summary["slices"].items():
            for key, values in groups.items():
                slice_rows.append({"id": experiment_id, "slice": slice_name, "value": key, **values})
    pd.DataFrame(slice_rows).to_csv(study_root / "all-slices.csv", index=False, encoding="utf-8", lineterminator="\n")

    result = {
        "schema": "score-v4-complete-result",
        "protocol": {
            "selection_data": "S1-S4 only; overlapping 61-day folds",
            "rounding": config["rounding"],
            "new_configuration_count": len(OOF_PATHS),
            "new_configuration_limit": config["new_configuration_limit"],
            "reserve_configurations_used": 2,
            "fixed_blends_are_not_new_fits": True,
            "blend_candidate_rule": (
                "B2-cal: best standalone new model; C1: best standalone non-HGBT family "
                "with lower residual correlation to B2. Only preregistered weights 0.10/0.25/0.50."
            ),
        },
        "baseline": {
            "id": "B2",
            "oof_path": str(baseline_path),
            "oof_sha256": sha256_file(baseline_path),
            "summary": baseline_summary,
            "platform_score": 0.84260,
            "competition_csv_sha256": "505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94",
        },
        "standalone": records,
        "fixed_blends": blend_records,
        "selection": {
            "eligible_ids": [record["id"] for record in eligible],
            "best_measured_new_id": best_new["id"],
            "best_measured_new_score": best_new["summary"]["rounded"]["score"],
            "best_measured_new_delta": best_new["admission"]["delta_score"],
            "frozen_finalists": [r["id"] for r in sorted(eligible, key=lambda r: -r["summary"]["rounded"]["score"])[:2]],
            "stress_folds_opened": False,
            "reused_D_opened": False,
            "new_competition_csv_prepared": False,
            "decision": "await_frozen_finalist_stress_and_D" if eligible else "retain_B2_no_candidate_met_preregistered_admission",
        },
        "protocol_deviations": [
            "First-pass A1/A2 inner tuning split origins but did not purge overlapping target dates. Corrected in protocol-repair; first-pass results retained and superseded.",
            "First-pass A1 root had no shrinkage toward 1. Added the requested L1 prior; the same bounds/strength grid was retained.",
            "First-pass daily diagnostics rounded sums. Final diagnostics sum rounded hours; hourly selection score was unaffected.",
            "A one-off exploratory command evaluated three fixed weights for N1 and D2 in addition to B2-cal/C1, exceeding the two-candidate blend budget. All six extra mixtures failed admission and were excluded from selection; they are retained in the deviation audit.",
            "Chronos N2 technical smoke used cross_learning=False (API default); the full preregistered representation run used cross_learning=True. Smoke quality is not used to select the model.",
        ],
        "external_actions": {
            "platform_upload": "not_performed",
            "server_update": "not_performed",
            "commit": "not_performed",
            "push": "not_performed",
        },
    }
    destination = study_root / "complete.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-root", default="artifacts/score-v4-20260926-r01")
    parser.add_argument("--baseline-root", default="artifacts/score-v3-20260926-r02")
    parser.add_argument("--config", default="ml/experiments/score-v4.json")
    args = parser.parse_args()
    result = run(Path(args.study_root), Path(args.baseline_root), Path(args.config))
    print(json.dumps(result["selection"], ensure_ascii=False))


if __name__ == "__main__":
    main()
