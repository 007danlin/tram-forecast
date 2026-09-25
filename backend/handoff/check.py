"""Compare a running API and CSV export to the supplied local forecast CSV."""

import argparse
import csv
import io
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

from backend.handoff.store import load_snapshot


def check(base_url: str, release: Path) -> None:
    snapshot = load_snapshot(release)

    def call(path, body=None):
        request = Request(
            base_url.rstrip("/") + "/api/v2/handoff/" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            return response.headers, response.read()

    _, raw = call("ready")
    if json.loads(raw)["forecast_run_id"] != snapshot.run_id:
        raise ValueError("Server is serving a different release")
    with (release / "forecast.csv").open(newline="", encoding="utf-8-sig") as file:
        original = list(csv.DictReader(file, delimiter=";"))
    dates = sorted({min(row["date"] for row in original), max(row["date"] for row in original)})
    from datetime import date, timedelta

    for first_date in dates:
        next_date = (date.fromisoformat(first_date) + timedelta(days=1)).isoformat()
        for route in snapshot.routes:
            body = {
                "route_ids": [route],
                "start": first_date + "T00:00:00+03:00",
                "end": next_date + "T00:00:00+03:00",
                "resolution": "hour",
                "forecast_run_id": snapshot.run_id,
            }
            expected = {
                int(row["hour"]): float(row["prediction"])
                for row in original
                if row["route"] == route and row["date"] == first_date
            }
            _, raw = call("query", body)
            hourly = json.loads(raw)
            if len(hourly["rows"]) != 24:
                raise ValueError("Expected 24 hourly cells")
            for hour, row in enumerate(hourly["rows"]):
                if row["value"] != expected.get(hour):
                    raise ValueError("CSV/API hourly value mismatch")
            _, raw = call("query", {**body, "resolution": "day"})
            daily = json.loads(raw)
            total = math.fsum(expected.values()) if expected else None
            if daily["rows"][0]["value"] != total:
                raise ValueError("CSV/API daily sum mismatch")
            headers, raw = call(
                "export", {**hourly["filters"], "expected_result_id": hourly["result_id"]}
            )
            exported = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            if headers["X-Result-Id"] != hourly["result_id"] or len(exported) != 24:
                raise ValueError("Export identity mismatch")
            for hour, row in enumerate(exported):
                value = float(row["value"]) if row["value"] else None
                if value != expected.get(hour):
                    raise ValueError("Export/source mismatch")
    print(
        f"PASS {len(snapshot.routes)} routes, dates {dates}: source CSV = hourly API = daily sums = exported CSV; {snapshot.run_id}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--release", required=True, type=Path)
    args = parser.parse_args()
    check(args.base_url, args.release)


if __name__ == "__main__":
    main()
