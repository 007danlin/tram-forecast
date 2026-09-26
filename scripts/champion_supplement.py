"""Add source receipts and saved-v3 evidence to a new copy of the G0 bundle.

No fit, threshold search, platform upload or server update. Downloads are public
reference pages only, bounded to 20 seconds per URL with normal TLS validation.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from scripts.champion_evidence import copy, key, read_csv, save, sha

URLS = {
    "calendar-government": "https://government.ru/docs/all/155500/",
    "calendar-cbr": "https://www.cbr.ru/other/holidays/",
    "weather-documentation": "https://open-meteo.com/en/docs/historical-weather-api",
    "T01-transport": "https://transport.mos.ru/mostrans/all_news/125272",
}


def fetch(item, dest):
    name, url = item
    body = dest / f"{name}.html"
    result = subprocess.run(["curl", "--location", "--silent", "--show-error",
                             "--max-time", "20", "--max-filesize", "4194304",
                             "--output", str(body), "--write-out", "%{http_code}", url],
                            text=True, capture_output=True)
    return {"url": url, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "curl_exit_code": result.returncode, "http_code": result.stdout,
            "error": result.stderr, "body": body.name if body.exists() else None,
            "sha256": sha(body) if body.exists() else None,
            "status": "received_needs_content_check" if result.returncode == 0 and result.stdout == "200" else "access_failed"}


def metrics(rows, rounded):
    actual = [float(r["boardings"]) for r in rows]
    prediction = [float(r["prediction"]) for r in rows]
    if not all(math.isfinite(p) and p >= 0 for p in prediction):
        raise ValueError("Invalid saved predictions")
    if rounded:
        prediction = [math.floor(p + .5) for p in prediction]
    total = math.fsum(actual)
    sae = math.fsum(abs(y-p) for y, p in zip(actual, prediction, strict=True))
    return {"rows": len(rows), "sum_y": total, "sae": sae,
            "score": max(0., 1-sae/total) if total else None,
            "bias": math.fsum(p-y for y, p in zip(actual, prediction, strict=True))}


def saved_v3(output):
    base = output / "evidence/score-v3/experiments"
    controls = read_csv(base / "B2/oof.csv", ",")
    keys = [(r["fold"], *key(r), r["boardings"]) for r in controls]
    summaries = {}
    for folder in sorted(base.iterdir()):
        rows = read_csv(folder / "oof.csv", ",")
        if [(r["fold"], *key(r), r["boardings"]) for r in rows] != keys:
            raise ValueError(f"Unequal saved OOF keys or targets: {folder.name}")
        record = json.loads((folder / "record.json").read_text())
        rounded = metrics(rows, True)
        if abs(rounded["score"] - record["summary"]["rounded"]["score"]) > 1e-12:
            raise ValueError(f"Saved metric differs: {folder.name}")
        summaries[folder.name] = {"rounded": rounded, "raw": metrics(rows, False),
             "oof_sha256": sha(folder / "oof.csv"),
             "folds": {fold: metrics([r for r in rows if r["fold"] == fold], True) for fold in ("S1", "S2", "S3", "S4")}}
    diagnostic = output / "evidence/score-v3/folds/D-B2/D/oof.csv"
    summaries["B2-reused-D"] = {"rounded": metrics(read_csv(diagnostic, ","), True),
                                  "raw": metrics(read_csv(diagnostic, ","), False),
                                  "oof_sha256": sha(diagnostic)}
    save(output / "evidence/v3-recomputed-no-fit.json", summaries)


def local_evidence(root, output):
    from ml.factors import official_calendar_2025
    calendar = official_calendar_2025()
    calendar.to_csv(output / "sources/calendar-2025.csv", index=False)
    expected = {"is_transferred_day_off": {"2025-05-02", "2025-05-08", "2025-06-13", "2025-11-03", "2025-12-31"},
                "is_working_weekend": {"2025-11-01"}}
    for flag, days in expected.items():
        actual = set(calendar.loc[calendar[flag].eq(1), "date"].dt.strftime("%Y-%m-%d"))
        if actual != days:
            raise ValueError(f"Calendar mismatch: {flag}")
    save(output / "sources/calendar-code-check.json", {
        "verified_sets": {k: sorted(v) for k, v in expected.items()},
        "all_365_dates": len(calendar) == 365, "feature_code_sha256": sha(root / "ml/factors.py"),
        "csv_sha256": sha(output / "sources/calendar-2025.csv"),
        "valid_at": "2025-01-01/2025-12-31", "norm_date": "2024-10-04",
        "available_at": "2024-10-04 (norm publication date; exact time not preserved)",
        "snapshot_acquired_at": datetime.now(timezone.utc).isoformat(),
        "join": "date, many-to-one; shared across 9 modeled routes",
        "runtime_network_dependency": False})
    weather = root / "artifacts/external/open-meteo"
    manifest = json.loads((weather / "moscow-2025-era5.manifest.json").read_text())
    for item in ("raw_snapshot", "normalized"):
        path = weather / manifest[item]["filename"]
        if sha(path) != manifest[item]["sha256"]:
            raise ValueError("Historical weather checksum mismatch")
    copy(weather / "moscow-2025-era5.manifest.json", output / "sources/weather-historical-manifest.json")
    save(output / "sources/weather-local-verification.json", {
        "raw_sha256": manifest["raw_snapshot"]["sha256"], "normalized_sha256": manifest["normalized"]["sha256"],
        "hashes_verified_now": True, "fetched_at": manifest["raw_snapshot"]["fetched_at"],
        "available_at": None, "availability_status": "reanalysis; not origin-issued forecast",
        "grain_join": "Moscow grid point × hourly timestamp, many-to-one across routes",
        "coverage_hours": 8760, "champion_dependency": False,
        "raw_and_normalized_not_embedded": "excluded factor, local hashes/manifest provided; no new acquisition of weather series"})


def finish(root, output):
    """Seal documentation/config evidence, preserving the original model and CSV."""
    import joblib
    from scripts.champion_evidence import CHAMPION
    from ml.cli import command_year_scenario
    from types import SimpleNamespace
    from datetime import date, timedelta
    provenance = json.loads((output / "provenance.json").read_text())
    for path in (output / "source/ml").glob("*.py"):
        if sha(path) != provenance["source_files_sha256"][str(path.relative_to(output / "source"))]:
            raise ValueError("Inference source changed after successful verification")
    artifact = joblib.load(output / "model/model.joblib")
    model = artifact["model"]
    config = {
        "extraction": "read actual serialized B2; no fit",
        "model_sha256": sha(output / "model/model.joblib"),
        "class": type(model).__name__, "seed": model.random_seed,
        "weights": model.parameter_manifest,
        "calendar_regressor": model.calendar_model_.pipeline_.named_steps["regressor"].get_params(),
        "interaction_regressor": model.interaction_model_.pipeline_.get_params(),
        "history_end": str(model.history_end_), "weather_included": model.include_weather,
    }
    save(output / "config-extracted.json", config)
    calendar = read_csv(output / "sources/calendar-2025.csv", ",")
    expected_public = {(date(2025, 1, 1) + timedelta(days=n)).isoformat() for n in range(8)} | {
        "2025-02-23", "2025-03-08", "2025-05-01", "2025-05-09", "2025-06-12", "2025-11-04"}
    if {r["date"] for r in calendar if r["is_public_holiday"] == "1"} != expected_public:
        raise ValueError("Public holiday dates mismatch")
    save(output / "sources/content-review.json", {
        "calendar_cbr_snapshot_sha256": sha(output / "sources/calendar-cbr.html"),
        "calendar_all_public_dates_checked": sorted(expected_public),
        "calendar_all_five_transfers_and_one_working_saturday_checked": True,
        "calendar_review_basis": "Manual comparison of 2025 CBR section, code and normalized snapshot; primary government URL timed out",
        "weather_docs_snapshot_sha256": sha(output / "sources/weather-documentation.html"),
        "weather_review": "ERA5 reanalysis, not origin-issued operational forecast",
        "T01_full_text_retrieved_now": False,
    })
    # Logs retain stderr, but it must not be mistaken for a requirement line.
    proc = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, check=True)
    (output / "requirements-inference.lock").write_text(proc.stdout)
    (output / "verification/pip-freeze-final.stderr.txt").write_text(proc.stderr)
    command_year_scenario(SimpleNamespace(output=str(output / "year-scenarios.json")))
    for src, dest in (
        ("ml/reports/champion-b2-g2-2026-09-26.md", "G2-model-passport.md"),
        ("ml/reports/v3-completion-and-g1-result-2026-09-26.md", "v3-status-and-G1.md"),
        ("ml/reports/champion-g0-readme.md", "G0-detailed-readme.md"),
        ("ml/reports/champion-final-readme.md", "README.md"),
        ("INTEGRATION.md", "documentation/INTEGRATION.md"),
        ("ml/README.md", "documentation/ml-README.md"),
        ("ml/reports/model-card.md", "documentation/model-card.md"),
        ("ml/external-sources.json", "sources/registry-current.json"),
        ("docs/team-specs/score-v3-sources.md", "sources/score-v3-sources.md"),
        ("scripts/champion_evidence.py", "source/scripts/champion_evidence.py"),
        ("scripts/champion_supplement.py", "source/scripts/champion_supplement.py"),
        ("tests/ml/test_champion_evidence.py", "source/tests/ml/test_champion_evidence.py"),
        ("docs/submission-final/b2-acceptance.md", "evidence/platform/b2-acceptance.md"),
        ("docs/submission-final/artifacts.md", "evidence/platform/artifacts.md"),
        ("docs/submission-final/verification.md", "evidence/platform/verification.md"),
    ):
        copy(root / src, output / dest)
    # Historical G0 source docs stay intact; current documents are explicit supplements.
    provenance["final_source_files_sha256"] = {
        str(p.relative_to(output / "source")): sha(p) for p in sorted((output / "source").rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts}
    provenance["g0_packaging_note"] = "Preliminary G0 lock captured a pip stderr warning. Final lock uses stdout only; model/predictions/inference code are unchanged."
    save(output / "provenance.json", provenance)
    checks = subprocess.run([sys.executable, "-m", "unittest", "tests.ml.test_champion_evidence",
                             "tests.ml.test_submission", "tests.ml.test_metrics", "tests.ml.test_data", "-v"],
                            cwd=output / "source", text=True, capture_output=True)
    (output / "verification/packaged-tests.log").write_text(checks.stdout + checks.stderr)
    if checks.returncode:
        raise ValueError("Packaged tests failed")
    deps = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--no-index",
                           "-r", str(output / "requirements-inference.lock")], text=True, capture_output=True)
    (output / "verification/lock-install-check.log").write_text(deps.stdout + deps.stderr)
    if deps.returncode:
        raise ValueError("Final dependency lock is not installable in the verified environment")
    audit = json.loads((output / "evidence/adaptive-csv-audit.json").read_text())
    if sha(output / "champion.csv") != CHAMPION:
        raise ValueError("Champion changed")
    if (output / "adaptive.csv").exists():
        (output / "adaptive.csv").rename(output / "evidence/adaptive/rejected-submission.csv")
    result = json.loads((output / "verification/result.json").read_text())
    save(output / "model-to-csv-manifest.json", {
        "model": {"path": "model/model.joblib", "sha256": sha(output / "model/model.joblib")},
        "float": {"path": "forecast-float.csv", "sha256": sha(output / "forecast-float.csv")},
        "submission": {"path": "champion.csv", "sha256": CHAMPION, "rows": 14640, "route5_zero_rows": 1464},
        "transform": "floor(max(float,0)+0.5) once; zero fallback route5",
        "all_rows_checked": result["float_roundtrip_all_rows"],
        "two_independent_cli_runs_match_sha": result["two_runs_equal_champion_sha256"],
        "handoff": result["handoff_receipt"],
        "platform_evidence": audit["platform_result"],
        "champion_decision": audit["decision"],
        "config_sha256": sha(output / "config-extracted.json"),
        "dependency_lock_sha256": sha(output / "requirements-inference.lock"),
        "source_provenance_sha256": sha(output / "provenance.json"),
        "full_file_inventory": "bundle-manifest.json",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--finish", action="store_true")
    args = parser.parse_args()
    root, output = Path.cwd(), args.output.resolve()
    if args.finish:
        finish(root, output)
        return
    if args.base is None:
        parser.error("--base is required unless --finish")
    shutil.copytree(args.base, output)
    (output / "sources").mkdir()
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda item: fetch(item, output / "sources"), URLS.items()))
    save(output / "sources/access-receipts.json", receipts)
    cbr = output / "sources/calendar-cbr.html"
    if cbr.exists():
        text = html.unescape(re.sub(r"<[^>]+>", " ", cbr.read_text()))
        text = re.sub(r"\s+", " ", text)
        start = text.find("Перечень дополнительных выходных дней в 2025")
        end = text.find("Информация о проведении торгов", start)
        if start >= 0 and end > start:
            (output / "sources/calendar-cbr-2025-extract.txt").write_text(text[start:end] + "\n")
    local_evidence(root, output)
    saved_v3(output)
    copy(root / "scripts/champion_supplement.py", output / "supplement-tools/champion_supplement.py")
    print(json.dumps({"output": str(output), "receipts": receipts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
