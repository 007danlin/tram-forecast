"""Package an ML artifact using the existing, strict handoff transport paths."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from backend.handoff.install import MEMBERS
from backend.handoff.store import digest, load_snapshot, read_limited, release_id

MODEL_FILES = set(MEMBERS) - {"forecast.csv"}
ROUTES = {"1", "5", "7", "11", "12", "17", "25", "26", "28", "50"}


def regular_file(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError(f"Symlinks are not accepted: {path}")
    if not path.is_file():
        raise ValueError(f"Required regular file is missing: {path}")
    return read_limited(path)


def package(artifact_dir: Path, forecast: Path, output: Path) -> str:
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    if output.exists() or output.is_symlink() or checksum_path.exists() or checksum_path.is_symlink():
        raise ValueError("Output already exists; choose a new release name")
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ValueError("Artifact must be a regular directory")
    if {p.name for p in artifact_dir.iterdir()} != MODEL_FILES:
        raise ValueError("Artifact must contain exactly the four handoff model files; additional factors require an agreed contract")
    blobs = {name: regular_file(artifact_dir / name) for name in MODEL_FILES}
    blobs["forecast.csv"] = regular_file(forecast)
    hashes = {name: digest(data) for name, data in blobs.items()}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".package-handoff-", dir=output.parent) as tmp:
        root = Path(tmp)
        for name, data in blobs.items():
            (root / name).write_bytes(data)
        (root / "receipt.json").write_text(json.dumps({
            "files": hashes, "forecast_run_id": release_id(hashes),
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }))
        snapshot = load_snapshot(root)  # same manifest/CSV validation as the receiver
        start = datetime.fromisoformat("2025-11-01T00:00:00+03:00")
        expected = {(route, start + timedelta(hours=h)) for route in ROUTES for h in range(61 * 24)}
        if set(snapshot.cells) != expected or set(snapshot.cold_routes) != {"5"}:
            raise ValueError("Expected all 14,640 route/date/hour cells for November–December 2025, with route 5 baseline")
        candidate = root / "handoff.zip"
        with ZipFile(candidate, "w", compression=ZIP_DEFLATED) as archive:
            for name, member in sorted(MEMBERS.items()):
                info = ZipInfo(member, date_time=(2025, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, blobs[name])
        checksum = digest(candidate.read_bytes())
        receipt = root / "archive.sha256"
        receipt.write_text(f"{checksum}  {output.name}\n", encoding="utf-8")
        # Hard links publish completed files atomically and refuse to overwrite,
        # including if another packager wins the race after the initial check.
        os.link(receipt, checksum_path)
        try:
            os.link(candidate, output)
        except BaseException:
            checksum_path.unlink()
            raise
    return checksum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--forecast", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(package(args.artifact_dir, args.forecast, args.output))


if __name__ == "__main__":
    main()
