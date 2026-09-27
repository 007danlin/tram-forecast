"""Freeze and verify the existing B2; never train, upload or deploy anything.

Local evidence bundles contain real predictions and must remain outside Git.
Run prepare with the repository Python, then verify with an isolated Python
from the copied source directory. Package only after verification succeeds.
"""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

CHAMPION = "505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94"
ADAPTIVE = "42ab12fbbe68afdbec9b915394fec66974f17e698506e76d80f2279af8d868da"
MODEL_FILES = ("model.joblib", "metadata.json", "feature-schema.json", "manifest.json")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def copy(source, dest):
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Not a regular file: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)


def read_csv(path, delimiter=";"):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


def key(row):
    return row["route"], row["date"], int(row["hour"])


def compare_csv(base_path, candidate_path):
    base, candidate = read_csv(base_path), read_csv(candidate_path)
    if len(base) != 14640 or [key(r) for r in base] != [key(r) for r in candidate]:
        raise ValueError("Sample keys/order/length differ")
    expected = {(route, (date(2025, 11, 1) + timedelta(days=day)).isoformat(), hour)
                for route in ("1", "5", "7", "11", "12", "17", "25", "26", "28", "50")
                for day in range(61) for hour in range(24)}
    if {key(r) for r in base} != expected:
        raise ValueError("Not the complete Nov-Dec 2025 sample grid")
    if any(list(r) != ["route", "date", "hour", "prediction"] for r in base + candidate):
        raise ValueError("Unexpected CSV columns")
    changed, allowed, checks = [], [], {}
    for a, b in zip(base, candidate, strict=True):
        day = date.fromisoformat(a["date"])
        ordinary = day.weekday() >= 5 and a["date"] != "2025-11-01"
        # Only Nov-Dec 2025: no statutory holiday falls on Sat/Sun.
        if a["route"] == "50" and ordinary:
            allowed.append(key(a))
        if a != b:
            changed.append(key(a))
    if not set(changed).issubset(allowed):
        raise ValueError("Changed rows outside planned route-50 ordinary weekends")
    if len({key(r) for r in base}) != 14640:
        raise ValueError("Duplicate keys")
    for name, rows in (("champion", base), ("adaptive", candidate)):
        values = [float(r["prediction"]) for r in rows]
        if not all(math.isfinite(v) and v >= 0 and v == int(v) for v in values):
            raise ValueError("Invalid submission values")
        zero5 = [r for r in rows if r["route"] == "5"]
        if len(zero5) != 1464 or any(float(r["prediction"]) for r in zero5):
            raise ValueError("Route 5 must be 1464 zeros")
        checks[name] = {"rows": len(rows), "sum_prediction": sum(map(int, values)),
                        "route5_zero_rows": len(zero5)}
    for day in ("2025-11-01", "2025-11-03", "2025-11-04", "2025-12-31"):
        before = [r for r in base if r["route"] == "50" and r["date"] == day]
        after = [r for r in candidate if r["route"] == "50" and r["date"] == day]
        if before != after or len(before) != 24:
            raise ValueError(f"Protected day changed: {day}")
        checks[day] = {"unchanged": True, "route50_total": sum(int(r["prediction"]) for r in before)}
    return {"champion_sha256": sha(base_path), "adaptive_sha256": sha(candidate_path),
            "keys_and_order_equal": True, "changed_rows": len(changed),
            "allowed_rows": len(allowed), "other_routes_unchanged": True,
            "changed_dates": sorted({k[1] for k in changed}), "checks": checks,
            "platform_result": {
                "champion": {"score": 0.84260, "status": "owner_confirmed_with_success_row_screenshot",
                             "screenshot_time": "2026-09-26T18:50:55+03:00",
                             "stable_submission_id": None, "form_receipt": None,
                             "screenshot_bytes_in_this_checkout": False},
                "adaptive": {"score": 0.83543, "status": "reported_by_user",
                             "receipt_id": None, "screenshot_available": False},
                "delta": -0.00717,
                "uploaded_bytes_independently_verified_by_this_script": False,
            },
            "decision": "reject_adaptive_keep_original_champion"}


def prepare(root, output, dataset):
    output.mkdir(parents=True, exist_ok=False)
    quality = root / "artifacts/quality-085"
    for name in MODEL_FILES:
        copy(quality / "calendar-interaction-ensemble" / name, output / "model" / name)
    copy(quality / "submission-calendar-interaction-ensemble-10-routes.csv", output / "champion.csv")
    copy(root / "artifacts/route50-adaptive-20260926-r01/submission-route50-adaptive-research.csv", output / "adaptive.csv")
    copy(dataset / "test_submission.csv", output / "template.csv")
    if sha(output / "champion.csv") != CHAMPION or sha(output / "adaptive.csv") != ADAPTIVE:
        raise ValueError("Unexpected historical CSV hash; do not associate the old score")
    manifest = json.loads((output / "model/manifest.json").read_text())
    for name, checksum in manifest["files"].items():
        if sha(output / "model" / name) != checksum:
            raise ValueError("Model manifest mismatch")
    if sha(output / "template.csv") != manifest["source_checksums"]["test_submission.csv"]:
        raise ValueError("Wrong sample")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    for name in tracked:
        if name and (name.startswith(("ml/", "backend/handoff/", "backend/contracts/", "tests/ml/"))
                     or name in ("backend/__init__.py", "scripts/__init__.py", "scripts/package_ml_handoff.py", "LICENSE")):
            copy(root / name, output / "source" / name)
    copy(root / "scripts/champion_evidence.py", output / "source/scripts/champion_evidence.py")
    copy(root / "ml/reports/champion-g0-readme.md", output / "README.md")
    for name in ("evaluation.json", "experiment-log.csv"):
        copy(quality / name, output / "evidence/quality-085" / name)
    v3 = root / "artifacts/score-v3-20260926-r02"
    for path in v3.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".csv", ".sha256", ".diff"):
            copy(path, output / "evidence/score-v3" / path.relative_to(v3))
    for name in ("complete.json", "submission-route50-adaptive-research.preflight.json", "fingerprint.json"):
        copy(root / "artifacts/route50-adaptive-20260926-r01" / name, output / "evidence/adaptive" / name)
    save(output / "evidence/adaptive-csv-audit.json", compare_csv(output / "champion.csv", output / "adaptive.csv"))
    source_hashes = {str(p.relative_to(output / "source")): sha(p) for p in sorted((output / "source").rglob("*")) if p.is_file()}
    save(output / "provenance.json", {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "champion_id": "calendar_interaction_ensemble", "champion_sha256": CHAMPION,
        "reproduction_source_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip(),
        "reproduction_source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root)),
        "training_commit": None, "training_commit_status": "not_recorded_in_original_artifact",
        "historical_report_reference": "93d1ab1; not proof of exact training checkout/dirty state",
        "original_training_full_lock": None,
        "inference_lock_status": "frozen from newly isolated reproduction environment",
        "seed": 20250925, "fit_performed": False,
        "source_files_sha256": source_hashes,
        "metadata_correction": "Original immutable metadata predates approval of zero fallback for route 5. Preserve bytes; full sample/zero5 approved by team per later clarification.",
        "raw_source_hashes": manifest["source_checksums"], "raw_csv_rehashed_this_run": False,
        "label_hashes_verified_now": {
            p.name: sha(p) for p in sorted((dataset / "labels").glob("*.csv"))},
        "missing": ["stable platform submission ID/form receipt; referenced success-row PNG is absent from this checkout",
                    "adaptive platform receipt/screenshot", "original training commit/dirty state/full transitive lock"],
    })


def verify(output):
    if sys.prefix == sys.base_prefix:
        raise ValueError("Run verification in an isolated venv")
    cfg = Path(sys.prefix) / "pyvenv.cfg"
    if "include-system-site-packages = false" not in cfg.read_text():
        raise ValueError("System-site-packages must be disabled")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    logs = output / "verification"
    logs.mkdir(exist_ok=False)
    def run(args, log):
        result = subprocess.run([sys.executable, *args], cwd=output / "source", env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (logs / log).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"Command failed: see {logs / log}")
        return result.stdout
    versions = run(["-m", "pip", "freeze"], "pip-freeze.txt")
    (output / "requirements-inference.lock").write_text(versions)
    run(["-m", "pip", "check"], "pip-check.txt")
    run(["-c", "import sys, platform, ml; print(sys.version); print(platform.platform()); print(ml.__file__); print(sys.path)"], "environment.txt")
    for number in (1, 2):
        dest = logs / f"run-{number}"
        dest.mkdir()
        run(["-m", "ml", "submission", "--artifact-dir", str(output / "model"),
             "--template", str(output / "template.csv"), "--scope", "sample",
             "--output", str(dest / "submission.csv"), "--preflight-output", str(dest / "preflight.json")], f"run-{number}.log")
        if sha(dest / "submission.csv") != CHAMPION:
            raise ValueError("Reproduced CSV differs from champion")
    run(["-m", "ml", "forecast", "--artifact-dir", str(output / "model"),
         "--start", "2025-11-01", "--end", "2025-12-31", "--output", str(output / "forecast-float.csv")], "forecast.log")
    floating = {key(r): float(r["prediction"]) for r in read_csv(output / "forecast-float.csv")}
    champion = read_csv(output / "champion.csv")
    if len(floating) != 14640 or any(math.floor(floating[key(r)] + .5) != int(r["prediction"]) for r in champion):
        raise ValueError("Float-to-DS roundtrip failed")
    run(["-m", "scripts.package_ml_handoff", "--artifact-dir", str(output / "model"),
         "--forecast", str(output / "forecast-float.csv"), "--output", str(output / "handoff-b2.zip")], "handoff-package.log")
    run(["-m", "backend.handoff.install", str(output / "handoff-b2.zip"), "--output", str(output / "handoff-local-check")], "handoff-install.log")
    save(logs / "result.json", {"two_runs_equal_champion_sha256": CHAMPION,
         "float_roundtrip_all_rows": True, "rows": 14640, "fit_performed": False,
         "clean_venv": True, "platform_upload": False, "server_update": False,
         "float_sha256": sha(output / "forecast-float.csv"),
         "handoff_zip_sha256": sha(output / "handoff-b2.zip"),
         "handoff_receipt": json.loads((output / "handoff-local-check/receipt.json").read_text())})


def bundle(output):
    result = json.loads((output / "verification/result.json").read_text())
    if result["two_runs_equal_champion_sha256"] != CHAMPION:
        raise ValueError("Verification required")
    files = [p for p in sorted(output.rglob("*")) if p.is_file()
             and "__pycache__" not in p.parts
             and p.suffix not in (".pyc", ".pyo")
             and p.name not in ("bundle-manifest.json", ".DS_Store")]
    save(output / "bundle-manifest.json", {"files": {str(p.relative_to(output)): sha(p) for p in files}})
    archive = output.with_suffix(".zip")
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as zipped:
        for p in [*files, output / "bundle-manifest.json"]:
            zipped.write(p, str(p.relative_to(output)))
    archive.with_suffix(".zip.sha256").write_text(f"{sha(archive)}  {archive.name}\n")
    print(json.dumps({"archive": str(archive), "sha256": sha(archive)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "bundle"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.action == "prepare":
        if args.dataset is None:
            parser.error("prepare requires --dataset")
        prepare(Path.cwd(), output, args.dataset)
    elif args.action == "verify":
        verify(output)
    else:
        bundle(output)


if __name__ == "__main__":
    main()
