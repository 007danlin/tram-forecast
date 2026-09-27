"""Package local score-v4 evidence without changing champion or publishing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from ml.score_v4 import sha256_file


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def package(root: Path, destination: Path) -> dict:
    if destination.exists() or destination.with_suffix(".zip").exists():
        raise ValueError("Choose a new evidence package path")
    complete = json.loads((root / "complete.json").read_text(encoding="utf-8"))
    if complete["selection"]["eligible_ids"]:
        raise ValueError("This package command is for the completed no-admission study")
    audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
    if not audit["champion_preflight"]["passed"]:
        raise ValueError("Champion preflight failed")
    destination.mkdir(parents=True)
    repo = Path(__file__).resolve().parent.parent
    # Symlinked cache is already copied once at study/internal-b2.
    shutil.copytree(root, destination / "study", ignore=lambda folder, names: [name for name in names if (Path(folder) / name).is_symlink()])
    for folder in ("ml", "backend", "tests"):
        shutil.copytree(repo / folder, destination / "source" / folder,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    for name in ("package_score_v4.py", "champion_evidence.py", "champion_supplement.py", "package_ml_handoff.py"):
        target = destination / "source" / "scripts" / name
        target.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(repo / "scripts" / name, target)
    for name in ("INTEGRATION.md", "AGENTS.md", "LICENSE"):
        shutil.copy2(repo / name, destination / "source" / name)
    controls = destination / "controls" / "experiments"
    for name in ("B0", "B1", "B2", "D-MAE"):
        target = controls / name
        target.mkdir(parents=True)
        shutil.copy2(repo / "artifacts" / "score-v3-20260926-r02" / "experiments" / name / "oof.csv", target / "oof.csv")

    environments = {}
    environment_dir = destination / "environment"
    environment_dir.mkdir()
    for name, interpreter in (
        ("main", repo / ".venv/bin/python"),
        ("chronos", repo / "artifacts/.score-v4-chronos-venv/bin/python"),
        ("stats", repo / "artifacts/.score-v4-stats-venv/bin/python"),
    ):
        freeze = subprocess.run([str(interpreter), "-m", "pip", "freeze", "--all"], check=True, text=True, capture_output=True)
        lock = environment_dir / f"{name}.lock"
        lock.write_text(freeze.stdout, encoding="utf-8")
        check = subprocess.run([str(interpreter), "-m", "pip", "check"], check=True, text=True, capture_output=True)
        version = subprocess.check_output([str(interpreter), "-c", "import sys; print(sys.version)"], text=True).strip()
        environments[name] = {"python": version, "lock_sha256": sha256_file(lock), "pip_check": check.stdout.strip()}
    checkpoint = Path.home() / ".cache/huggingface/hub/models--amazon--chronos-2/snapshots/29ec3766d36d6f73f0696f85560a422f50e8498c"
    checkpoint_hashes = {name: sha256_file(checkpoint / name) for name in ("config.json", "model.safetensors")}
    _json(environment_dir / "receipt.json", {"environments": environments, "checkpoint_revision": checkpoint.name, "checkpoint_hashes": checkpoint_hashes,
                                          "checkpoint_weights_included": False, "checkpoint_source": "https://huggingface.co/amazon/chronos-2"})
    _json(destination / "champion-reference.json", {"hashes": audit["champion_hashes"], "preflight": audit["champion_preflight"],
                                                  "platform_score": 0.84260, "receipt_status": "owner confirmation; stable submission ID absent; original G0/G2 evidence retained unchanged"})
    verification_path = root / "verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8")) if verification_path.exists() else {
        "test_receipt": "not_supplied; packaging does not imply tests were run"
    }
    verification["serialized_models"] = {"count": len(audit["new_process_serialization"]), "max_abs_difference": max(x["max_abs_difference"] for x in audit["new_process_serialization"])}
    _json(destination / "verification.json", verification)
    readme = """# Score v4 evidence — 27.09.2026

Result: retain exact B2 (reported platform 0.84260). Twelve configurations and
six admitted-for-comparison fixed mixtures failed the unchanged promotion
criteria. Best local mixture: 0.84565649, delta +0.00081500, 2/4 improved folds.
No new competition CSV, upload, deployment, commit or push.

Start with source/ml/reports/score-v4-2026-09-27.md and study/complete.json.
study/full-experiment-journal.csv and study/all-slices.csv contain the full
aggregate comparison. Raw OOF and fitted fold models remain local evidence.
First-pass results are preserved; final A/B use study/protocol-repair.
study/audit.json contains origin grids, component diagnostics, serialization,
champion preflight and disclosed out-of-budget mixtures (excluded from selection).

All hashes are in manifest.json. Check ZIP CRC and every manifest entry before
using model files. Load joblib files only from a trusted package.
Original B2 CSV/float/model are referenced by SHA in champion-reference.json;
the G0/G2 package is preserved separately, not rebuilt here. Organizer labels
and pretrained Chronos weights are not included. The latter's pinned revision
and local SHA are in environment/receipt.json.

For a full replay, create three Python 3.12 environments and install the exact
main.lock, stats.lock and chronos.lock respectively. Use the commands in the
Russian report from the source/ directory, supplying the original dataset and
controls/experiments as the baseline directory. N/C --b2-oof must point to
controls/experiments/B2/oof.csv. Choose new output paths; do not overwrite study/.
The corrected A/B runner needs no repair pass. Reserve and audit use corrected
fold models from the root if no protocol-repair directory is present.

Read-only recomputation from existing OOF (from source/; this writes only summary
artifacts, no fitting):

    python -m ml.score_v4_finalize --study-root ../study --baseline-root ../controls

The finalizer rewrites summaries with paths for the current location. Keep the
original package intact and recompute into a copied study if bytewise manifest
verification is still needed. For inference audit also supply the original B2
package path with --champion-root and the unchanged dataset --dataset-dir.

Technical limitations and protocol repairs are explicit in the report. All S
windows overlap; D was previously used and was not reevaluated in v4. No result
in this bundle is evidence that the platform objective 0.95 has been reached.
"""
    (destination / "README.md").write_text(readme, encoding="utf-8")
    files = {str(path.relative_to(destination)): sha256_file(path) for path in sorted(destination.rglob("*")) if path.is_file()}
    manifest = {"schema": "score-v4-evidence", "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "git_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=repo).strip(),
                "code_status": "uncommitted working-tree sources captured by SHA; not claimed as the base commit", "files": files}
    _json(destination / "manifest.json", manifest)
    archive = destination.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(destination))
    with zipfile.ZipFile(archive) as zipped:
        bad = zipped.testzip()
        if bad is not None:
            raise ValueError(f"ZIP CRC failed: {bad}")
    digest = sha256_file(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return {"archive": str(archive), "sha256": digest, "manifest_files": len(files), "bytes": archive.stat().st_size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-root", type=Path, default=Path("artifacts/score-v4-20260926-r01"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/score-v4-evidence-20260927"))
    args = parser.parse_args()
    print(json.dumps(package(args.study_root, args.output), ensure_ascii=False))
