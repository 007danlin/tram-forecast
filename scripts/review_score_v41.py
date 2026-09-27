"""Independent stdlib-only verification of the two preregistered v4.1 OOFs."""

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from scripts.review_score_v4 import calculate


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def verify(root, config_path, source_path, champion, output):
    complete = json.loads((root / "complete.json").read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not config["registered_before_scoring"] or config["budget"]["v41_registered"] != 2:
        raise ValueError("Invalid v4.1 preregistration")
    if complete["config_sha256"] != digest(config_path) or complete["source_sha256"] != digest(source_path):
        raise ValueError("Config/source hash mismatch")
    with (champion / "sources/calendar-2025.csv").open(encoding="utf-8", newline="") as stream:
        calendar = {}
        for row in csv.DictReader(stream):
            calendar[row["date"]] = (
                "holiday" if int(row["is_public_holiday"]) or int(row["is_transferred_day_off"])
                else "working_saturday" if int(row["is_working_weekend"])
                else "day_off" if int(row["is_day_off"]) else "workday"
            )
    baseline, tasks = calculate(Path(complete["baseline_path"]), calendar)
    shape_metric, _ = calculate(Path(complete["shape_path"]), calendar, tasks)
    if baseline["oof_sha256"] != complete["baseline_sha256"] or shape_metric["oof_sha256"] != complete["shape_sha256"]:
        raise ValueError("Frozen B2/A2 input SHA mismatch")
    baseline_rows = read_rows(complete["baseline_path"])
    a2_rows = read_rows(complete["shape_path"])
    if len(baseline_rows) != len(a2_rows):
        raise ValueError("Frozen B2/A2 input length mismatch")
    results = {}
    day_totals = defaultdict(lambda: [0.0, 0.0, 0.0])
    for b2, a2 in zip(baseline_rows, a2_rows):
        key = (b2["fold"], b2["route"], b2["date"])
        day_totals[key][0] += float(b2["prediction"])
        day_totals[key][1] += max(float(a2["prediction"]), 0.0)
    for name in ("P1", "P2"):
        path = root / name / "oof.csv"
        metric, _ = calculate(path, calendar, tasks)
        record = complete["records"][name]
        expected = record["summary"]["rounded"]
        if metric["oof_sha256"] != record["oof_sha256"]:
            raise ValueError(f"OOF SHA mismatch for {name}")
        for actual, reported in ((metric["overall"]["rows"], expected["rows"]),
                                 (metric["overall"]["sum_y"], expected["sum_y"]),
                                 (metric["overall"]["sae"], expected["absolute_error"]),
                                 (metric["overall"]["score"], expected["score"])):
            if abs(actual - reported) > 1e-12:
                raise ValueError(f"Independent metric mismatch for {name}")
        candidate_rows = read_rows(path)
        for b2, a2, candidate in zip(baseline_rows, a2_rows, candidate_rows):
            key = (b2["fold"], b2["route"], b2["date"])
            day_totals[key][2] += float(candidate["prediction"])
            b = float(b2["prediction"])
            expected_p1 = b if day_totals[key][1] == 0 else day_totals[key][0] * max(float(a2["prediction"]), 0.0) / day_totals[key][1]
            expected_prediction = expected_p1 if name == "P1" else 0.5 * (b + expected_p1)
            if not math.isclose(float(candidate["prediction"]), expected_prediction, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"Formula mismatch for {name}/{key}")
        max_daily_difference = max(abs(values[2] - values[0]) for values in day_totals.values())
        if max_daily_difference > 1e-8:
            raise ValueError(f"Daily float volume changed for {name}: {max_daily_difference}")
        results[name] = {
            "overall": metric["overall"], "delta": metric["overall"]["score"] - baseline["overall"]["score"],
            "fold_deltas": {fold: values["score"] - baseline["slices"]["fold"][fold]["score"] for fold, values in metric["slices"]["fold"].items()},
            "route": metric["slices"]["route"], "day_type": metric["slices"]["day_type"],
            "h31_61": metric["slices"]["horizon"]["31-61"], "max_float_daily_total_difference": max_daily_difference,
            "oof_sha256": digest(path), "admission": record["admission"],
        }
        for values in day_totals.values():
            values[2] = 0.0
    audit = {
        "review_kind": "same-session self-review with independent stdlib arithmetic",
        "formula_uses_targets": False,
        "config_sha256": digest(config_path), "source_sha256": digest(source_path),
        "baseline": baseline["overall"], "results": results,
        "winner_after_S": complete["winner_after_S"], "budget_used": complete["budget_used"],
        "errors": [],
    }
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with output.with_name("v41-ledger.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = ["id", "hypothesis", "status", "config_sha256", "source_sha256", "oof", "oof_sha256", "score", "delta", "h31_61_score", "D_status", "stress_status", "platform_score", "decision"]
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for name, result in results.items():
            writer.writerow({
                "id": name, "hypothesis": "A2 hourly shape projected onto exact B2 float daily total" if name == "P1" else "50% shrinkage from B2 toward P1 shape",
                "status": "completed_rejected", "config_sha256": audit["config_sha256"], "source_sha256": audit["source_sha256"],
                "oof": str(root / name / "oof.csv"), "oof_sha256": result["oof_sha256"], "score": result["overall"]["score"], "delta": result["delta"],
                "h31_61_score": result["h31_61"]["score"], "D_status": "not_opened_no_S_finalist", "stress_status": "not_opened_no_S_finalist",
                "platform_score": "", "decision": "rejected_combined_gain_below_minimum",
            })
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("artifacts/score-v41-20260927-r01"))
    parser.add_argument("--config", type=Path, default=Path("ml/experiments/score-v41.json"))
    parser.add_argument("--source", type=Path, default=Path("ml/score_v41.py"))
    parser.add_argument("--champion", type=Path, default=Path("artifacts/champion-b2-g0-g2-20260926-final-v2"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/score-v4-review-20260927/independent-v41-audit.json"))
    args = parser.parse_args()
    verify(args.root, args.config, args.source, args.champion, args.output)
