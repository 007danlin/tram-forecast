"""Independent stdlib-only arithmetic and artifact review of v4.

This is a same-session self-review. It deliberately does not import the
training pipeline, pandas, NumPy, or any project metric/rounding helper.
"""

import argparse
from collections import defaultdict
import csv
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import zipfile


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _finish(values):
    n, total, error, bias = values
    return {"rows": n, "sum_y": total, "sae": error, "bias": bias,
            "mae": error / n if n else None,
            "score": max(0., 1. - error / total) if total else None}


def calculate(path, calendar, expected=None):
    tasks, groups, daily = [], defaultdict(lambda: [0, 0, 0, 0]), defaultdict(lambda: [0, 0])
    seen = set()
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            route, hour, y = int(row["route"]), int(row["hour"]), int(row["boardings"])
            day, fold, h = date.fromisoformat(row["date"]), row["fold"], int(row["horizon_day"])
            raw = float(row["prediction"])
            if not math.isfinite(raw) or raw < 0 or y < 0 or not 0 <= hour < 24 or not 1 <= h <= 61:
                raise ValueError(f"Invalid OOF row in {path}")
            key = (fold, route, day.isoformat(), hour)
            if key in seen:
                raise ValueError(f"Duplicate task: {key}")
            seen.add(key)
            tasks.append((*key, y, h))
            p = math.floor(max(raw, 0.) + .5)
            error, bias = abs(y - p), p - y
            horizon = "1-7" if h <= 7 else ("8-30" if h <= 30 else "31-61")
            kind = calendar[day.isoformat()]
            for name, value in (("all", "all"), ("fold", fold), ("route", str(route)),
                                ("hour", str(hour)), ("day_type", kind), ("horizon", horizon)):
                bucket = groups[name, value]
                for index, number in enumerate((1, y, error, bias)):
                    bucket[index] += number
            values = daily[fold, route, day.isoformat()]
            values[0] += y
            values[1] += p
    if expected is not None and tasks != expected:
        raise ValueError(f"OOF target/key/order/horizon differs: {path}")
    result = {"overall": _finish(groups["all", "all"]), "slices": {}}
    for (name, value), numbers in sorted(groups.items()):
        if name != "all":
            result["slices"].setdefault(name, {})[value] = _finish(numbers)
    result["daily_sae"] = sum(abs(y - p) for y, p in daily.values())
    result["unique_dates"] = len({x[2] for x in tasks})
    result["oof_sha256"] = digest(path)
    return result, tasks


def review(study, package, output, champion):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Review output already contains results")
    output.mkdir(exist_ok=True, parents=True)
    config_path = Path("ml/experiments/score-v4.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    report = json.loads((study / "complete.json").read_text(encoding="utf-8"))
    with (champion / "sources/calendar-2025.csv").open(encoding="utf-8", newline="") as stream:
        calendar = {}
        for row in csv.DictReader(stream):
            calendar[row["date"]] = (
                "holiday" if int(row["is_public_holiday"]) or int(row["is_transferred_day_off"])
                else "working_saturday" if int(row["is_working_weekend"])
                else "day_off" if int(row["is_day_off"]) else "workday"
            )
    source_hashes = {}
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if archive.testzip() is not None:
            raise ValueError("v4 archive CRC mismatch")
        for name, expected_sha in manifest["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected_sha:
                raise ValueError(f"v4 manifest mismatch: {name}")
            if name.startswith("source/"):
                source_hashes[name.removeprefix("source/")] = expected_sha
    baseline, tasks = calculate(report["baseline"]["oof_path"], calendar)
    assert baseline["overall"]["rows"] == 52704
    assert baseline["overall"]["sum_y"] == 44560499
    assert baseline["overall"]["sae"] == 6913941
    expected_tasks = set()
    for fold in config["folds"]:
        start = date.fromisoformat(fold["start"])
        assert date.fromisoformat(fold["train_end"]) == start - timedelta(days=1)
        for horizon in range(1, 62):
            for route in (1, 7, 11, 12, 17, 25, 26, 28, 50):
                for hour in range(24):
                    expected_tasks.add((fold["id"], route, (start + timedelta(days=horizon - 1)).isoformat(), hour, horizon))
    assert {(f, r, d, h, horizon) for f, r, d, h, y, horizon in tasks} == expected_tasks
    records, journal = {}, []
    all_records = {"B2": report["baseline"], **report["standalone"], **report["fixed_blends"]}
    for name, original in all_records.items():
        result, _ = calculate(original["oof_path"], calendar, tasks)
        if result["oof_sha256"] != original["oof_sha256"]:
            raise ValueError(f"Reported OOF SHA differs: {name}")
        rounded = original["summary"]["rounded"]
        for field, original_field in (("rows", "rows"), ("sum_y", "sum_y"), ("sae", "absolute_error"), ("bias", "signed_bias"), ("score", "score")):
            if abs(result["overall"][field] - rounded[original_field]) > 1e-12:
                raise ValueError(f"Reported metric differs: {name}/{field}")
        if result["daily_sae"] != original["summary"]["daily"]["absolute_error"]:
            raise ValueError(f"Daily rounding mismatch: {name}")
        result["delta"] = result["overall"]["score"] - baseline["overall"]["score"]
        result["fold_deltas"] = {key: value["score"] - baseline["slices"]["fold"][key]["score"] for key, value in result["slices"]["fold"].items()}
        records[name] = result
        journal.append({"id": name, "hypothesis": original.get("hypothesis", "exact incumbent"),
                        "status": "completed_control" if name == "B2" else "completed_rejected",
                        "config_sha256": digest(Path("ml/experiments/score-v4-reserve.json")) if name in ("R1", "R2") else digest(config_path),
                        "source_hash_reference": "source-hashes.json (packaged snapshot; not necessarily original execution timestamp)",
                        "oof": original["oof_path"], "oof_sha256": result["oof_sha256"],
                        "score": result["overall"]["score"], "delta": result["delta"],
                        "h31_61_score": result["slices"]["horizon"]["31-61"]["score"],
                        "D_status": "historical_reused_diagnostic" if name == "B2" else "not_opened_no_finalist",
                        "stress_status": "not_opened_no_finalist", "platform_score": .84260 if name == "B2" else None,
                        "decision": "preserve" if name == "B2" else original["decision"]})
    # Independently verify exact float -> DS and retained complete organizer grid.
    with (champion / "forecast-float.csv").open(encoding="utf-8", newline="") as stream:
        float_rows = list(csv.DictReader(stream, delimiter=";"))
    with (champion / "champion.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        assert reader.fieldnames == ["route", "date", "hour", "prediction"]
        ds_rows = list(reader)
    with (champion / "template.csv").open(encoding="utf-8", newline="") as stream:
        template = list(csv.DictReader(stream, delimiter=";"))
    float_lookup = {(int(r["route"]), r["date"], int(r["hour"])): float(r["prediction"]) for r in float_rows}
    ds_keys = [(int(r["route"]), r["date"], int(r["hour"])) for r in ds_rows]
    template_keys = [(int(r["route"]), r["date"], int(r["hour"])) for r in template]
    assert ds_keys == template_keys and len(ds_keys) == len(set(ds_keys)) == 14640
    zero5 = 0
    for key, row in zip(ds_keys, ds_rows):
        raw = float_lookup[key]
        p = int(row["prediction"])
        assert math.isfinite(raw) and raw >= 0 and p == math.floor(raw + .5)
        if key[0] == 5:
            assert p == 0
            zero5 += 1
    assert zero5 == 1464
    ds_sha = digest(champion / "champion.csv")
    assert ds_sha == "505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94"
    result = {"review_kind": "same-session self-review with independent stdlib arithmetic",
              "review_started_utc": "2026-09-27T06:03:50Z", "work_deadline_utc": "2026-09-27T09:03:50Z",
              "v4_package_sha256": digest(package), "v4_manifest_files_checked": len(manifest["files"]),
              "v4_used_configurations": 12, "v41_budget": 2,
              "records": records, "champion_export": {"rows": len(ds_rows), "route5_zeros": zero5, "sha256": ds_sha, "all_float_roundings_match": True},
              "errors": []}
    (output / "independent-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "source-hashes.json").write_text(json.dumps(source_hashes, indent=2) + "\n", encoding="utf-8")
    with (output / "review-ledger.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(journal[0])); writer.writeheader(); writer.writerows(journal)
    print(json.dumps({"verified_oof": len(records), "verified_manifest": len(manifest["files"]), "B2": baseline["overall"], "champion": result["champion_export"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, default=Path("artifacts/score-v4-20260926-r01"))
    parser.add_argument("--package", type=Path, default=Path("artifacts/score-v4-evidence-20260927.zip"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/score-v4-review-20260927"))
    parser.add_argument("--champion", type=Path, default=Path("artifacts/champion-b2-g0-g2-20260926-final-v2"))
    args = parser.parse_args()
    review(args.study, args.package, args.output, args.champion)
