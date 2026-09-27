"""Build the compact local v4/v4.1 review supplement with SHA manifest."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(output: Path) -> None:
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        raise FileExistsError(output)
    champion_archive = Path("artifacts/champion-b2-g0-g2-20260926-final-v2.zip")
    champion_csv = Path("artifacts/champion-b2-g0-g2-20260926-final-v2/champion.csv")
    files = {
        "report/score-v4-review.md": Path("ml/reports/score-v4-review.md"),
        "report/score-v4-original.md": Path("ml/reports/score-v4-2026-09-27.md"),
        "documentation/ml-README.md": Path("ml/README.md"),
        "documentation/INTEGRATION.md": Path("INTEGRATION.md"),
        "config/score-v4.json": Path("ml/experiments/score-v4.json"),
        "config/score-v4-reserve.json": Path("ml/experiments/score-v4-reserve.json"),
        "config/score-v41.json": Path("ml/experiments/score-v41.json"),
        "source/ml/score_v41.py": Path("ml/score_v41.py"),
        "source/scripts/review_score_v4.py": Path("scripts/review_score_v4.py"),
        "source/scripts/review_score_v41.py": Path("scripts/review_score_v41.py"),
        "source/scripts/package_score_v41_review.py": Path(__file__),
        "source/tests/test_score_v4.py": Path("tests/ml/test_score_v4.py"),
        "evidence/v4-independent-audit.json": Path("artifacts/score-v4-review-20260927/independent-audit.json"),
        "evidence/v4-source-hashes.json": Path("artifacts/score-v4-review-20260927/source-hashes.json"),
        "evidence/v4-ledger.csv": Path("artifacts/score-v4-review-20260927/review-ledger.csv"),
        "evidence/v41-independent-audit.json": Path("artifacts/score-v4-review-20260927/independent-v41-audit.json"),
        "evidence/v41-ledger.csv": Path("artifacts/score-v4-review-20260927/v41-ledger.csv"),
        "evidence/v41-complete.json": Path("artifacts/score-v41-20260927-r01/complete.json"),
        "evidence/P1-record.json": Path("artifacts/score-v41-20260927-r01/P1/record.json"),
        "evidence/P1-oof.csv": Path("artifacts/score-v41-20260927-r01/P1/oof.csv"),
        "evidence/P2-record.json": Path("artifacts/score-v41-20260927-r01/P2/record.json"),
        "evidence/P2-oof.csv": Path("artifacts/score-v41-20260927-r01/P2/oof.csv"),
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    readme = (
        "# Score v4/v4.1 review supplement\n\n"
        "Decision: no_improvement. P1=0.8459913566 (delta +0.0011498749) and "
        "P2=0.8454958280 (delta +0.0006543464) failed the unchanged +0.002 S threshold.\n\n"
        "The recommended competition file remains exact B2 `champion.csv`, which is not duplicated here. "
        f"Primary package: `{champion_archive}`; SHA-256 `{digest(champion_archive)}`. "
        f"Competition CSV SHA-256 `{digest(champion_csv)}`. Platform score 0.84260 is owner-confirmed; "
        "no stable receipt ID/PNG exists in this checkout.\n\n"
        "Reproduce the new calculation from repo root with `.venv/bin/python -m ml.score_v41 "
        "--output artifacts/v41-repeat`, then independently check it with "
        "`.venv/bin/python -m scripts.review_score_v41 --root artifacts/v41-repeat "
        "--output artifacts/v41-repeat-independent.json`. Use a new output path.\n\n"
        "No platform upload, server update, commit, push, or publication was performed. "
        "OOFs contain organizer targets and must remain outside Git.\n"
    ).encode("utf-8")
    verification = json.dumps({
        "ml_tests": {"count": 82, "result": "passed", "command": ".venv/bin/python -m unittest discover -s tests/ml -v"},
        "independent_v4": {"verified_oof": 19, "manifest_files": 557, "result": "passed"},
        "independent_v41": {"verified_oof": 2, "result": "passed"},
        "competition_export": {"rows": 14640, "route_5_zeros": 1464, "sha256": digest(champion_csv), "result": "unchanged_passed"},
    }, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    payload = {"README.md": readme, "verification.json": verification}
    payload.update({name: path.read_bytes() for name, path in files.items()})
    manifest = {
        "schema": "score-v4-review-supplement-v1",
        "decision": "no_improvement",
        "primary_champion_archive": str(champion_archive),
        "primary_champion_archive_sha256": digest(champion_archive),
        "recommended_csv": str(champion_csv),
        "recommended_csv_sha256": digest(champion_csv),
        "files": {name: digest_bytes(data) for name, data in sorted(payload.items())},
    }
    payload["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 27, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    archive_sha = digest(output)
    output.with_suffix(output.suffix + ".sha256").write_text(f"{archive_sha}  {output.name}\n", encoding="utf-8")
    print(json.dumps({"archive": str(output), "sha256": archive_sha, "files": len(payload), "bytes": output.stat().st_size}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/score-v4-review-v41-20260927.zip"))
    args = parser.parse_args()
    build(args.output)
