"""Import only known handoff files; never execute or deserialize the model."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
from zipfile import ZipFile

from backend.handoff.store import MAX_FILE_BYTES, digest, load_snapshot, release_id

MEMBERS = {
    **{
        name: f"artifacts/calendar-hgbt-v1/{name}"
        for name in (
            "metadata.json",
            "manifest.json",
            "feature-schema.json",
            "model.joblib",
        )
    },
    "forecast.csv": "artifacts/forecast-for-backend.csv",
}


def install(archive: Path, output: Path) -> str:
    if output.exists():
        raise ValueError("Output exists; use a new release directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".handoff-", dir=output.parent))
    try:
        hashes = {}
        with ZipFile(archive) as source:
            for name, member in MEMBERS.items():
                if (
                    source.namelist().count(member) != 1
                    or source.getinfo(member).file_size > MAX_FILE_BYTES
                ):
                    raise ValueError("Missing, duplicate or oversized archive member")
                with source.open(member) as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise ValueError("Oversized archive member")
                (temp / name).write_bytes(data)
                hashes[name] = digest(data)
        receipt = {
            "forecast_run_id": release_id(hashes),
            "files": hashes,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "note": "Local import receipt; CSV is not covered by the original ML manifest.",
        }
        (temp / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        snapshot = load_snapshot(temp)
        temp.rename(output)
        return snapshot.run_id
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(install(args.archive, args.output))


if __name__ == "__main__":
    main()
