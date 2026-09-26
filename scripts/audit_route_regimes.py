"""Stream raw organizer CSVs and audit route 7/17/50 regime changes.

The script never mutates the source data and never loads a full raw CSV into
memory.  It stores only daily counts and small sets of operational identifiers.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from ml.artifact import sha256_file
from ml.data import load_organizer_labels


ROUTES = (7, 17, 50)
USECOLS = (
    "tran_date_time",
    "validation_result",
    "ngpt_route",
    "device_no",
    "garage_number",
    "bus_exit_no",
)


def _serialise(value):
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    raise TypeError(type(value).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--chunksize", type=int, default=500_000)
    args = parser.parse_args()
    if args.chunksize <= 0:
        raise ValueError("chunksize must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    route_values: Counter[str] = Counter()
    invalid_route_values: Counter[str] = Counter()
    daily_counts: Counter[tuple[int, pd.Timestamp, str]] = Counter()
    identifiers: dict[tuple[int, pd.Timestamp, str], set[str]] = defaultdict(set)
    files = [args.dataset_dir / "train.csv", args.dataset_dir / "test.csv"]
    processed_rows = 0

    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
        for chunk in pd.read_csv(
            path,
            sep=";",
            usecols=list(USECOLS),
            dtype="string",
            chunksize=args.chunksize,
        ):
            processed_rows += len(chunk)
            route_values.update(chunk["ngpt_route"].dropna().tolist())
            route_text = chunk["ngpt_route"].str.extract(r"^(\d+)\s+\u0442\u0440\u0430\u043c\u0432\u0430\u0439$", expand=False)
            invalid = chunk.loc[chunk["ngpt_route"].notna() & route_text.isna(), "ngpt_route"]
            invalid_route_values.update(invalid.tolist())
            selected = route_text.isin([str(route) for route in ROUTES])
            if not selected.any():
                continue
            part = chunk.loc[selected, list(USECOLS)].copy()
            part["route"] = route_text.loc[selected].astype("int16")
            timestamp = pd.to_datetime(
                part["tran_date_time"],
                format="%Y-%m-%d %H:%M:%S",
                errors="raise",
            )
            part["date"] = timestamp.dt.normalize()
            part["is_success"] = part["validation_result"].eq("1")
            grouped = part.groupby(["route", "date"], sort=False)
            for (route, date), group in grouped:
                key = (int(route), date)
                daily_counts[(*key, "raw_rows")] += len(group)
                daily_counts[(*key, "successful_boardings")] += int(group["is_success"].sum())
                for column in ("device_no", "garage_number", "bus_exit_no"):
                    values = group.loc[group["is_success"], column].dropna().astype(str)
                    identifiers[(*key, column)].update(values.tolist())

    rows = []
    day_keys = sorted({(route, date) for route, date, _ in daily_counts})
    for route, date in day_keys:
        raw_rows = daily_counts[(route, date, "raw_rows")]
        successful = daily_counts[(route, date, "successful_boardings")]
        rows.append(
            {
                "route": route,
                "date": date,
                "raw_rows": raw_rows,
                "successful_boardings": successful,
                "success_share": successful / raw_rows if raw_rows else None,
                "successful_devices": len(identifiers[(route, date, "device_no")]),
                "successful_vehicles": len(identifiers[(route, date, "garage_number")]),
                "successful_runs": len(identifiers[(route, date, "bus_exit_no")]),
            }
        )
    daily = pd.DataFrame(rows).sort_values(["route", "date"], ignore_index=True)

    labels = load_organizer_labels(
        args.dataset_dir,
        "2025-01-01",
        "2025-10-31",
    )
    labels = labels[labels["route"].isin(ROUTES)].copy()
    label_daily = labels.groupby(["route", "date"], as_index=False).boardings.sum()
    comparison = label_daily.merge(
        daily[["route", "date", "successful_boardings"]],
        on=["route", "date"],
        how="left",
        validate="one_to_one",
    ).fillna({"successful_boardings": 0})
    comparison["difference"] = comparison["successful_boardings"] - comparison["boardings"]
    if comparison["difference"].ne(0).any():
        raise ValueError("Streamed route totals disagree with organizer labels")

    daily["allowed_history"] = daily["date"].between("2025-01-01", "2025-10-31")
    daily["month"] = daily["date"].dt.to_period("M").astype(str)
    daily["weekend"] = daily["date"].dt.dayofweek.ge(5)
    history_daily = daily[daily["allowed_history"]].copy()
    monthly = (
        history_daily.groupby(["route", "month", "weekend"], as_index=False)
        .agg(
            days=("date", "nunique"),
            mean_boardings=("successful_boardings", "mean"),
            median_boardings=("successful_boardings", "median"),
            mean_devices=("successful_devices", "mean"),
            min_devices=("successful_devices", "min"),
            mean_vehicles=("successful_vehicles", "mean"),
            mean_runs=("successful_runs", "mean"),
        )
    )
    focus = history_daily[
        ((history_daily.route.eq(17)) & history_daily.date.between("2025-03-15", "2025-05-31"))
        | ((history_daily.route.isin([7, 50])) & history_daily.date.between("2025-06-01", "2025-08-31"))
        | ((history_daily.route.eq(50)) & history_daily.date.between("2025-09-01", "2025-10-31"))
    ].copy()

    daily.to_csv(args.output_dir / "route-day-raw-coverage.csv", index=False)
    monthly.to_csv(args.output_dir / "route-month-daytype.csv", index=False)
    focus.to_csv(args.output_dir / "focus-route-days.csv", index=False)
    report = {
        "purpose": "read-only route regime audit; no target repair or deletion",
        "source_files": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in files
        },
        "processed_rows": processed_rows,
        "selected_routes": list(ROUTES),
        "label_daily_rows": len(comparison),
        "label_raw_daily_mismatches": int(comparison.difference.ne(0).sum()),
        "forbidden_tail_after_2025_10_31": {
            "route_days": int((~daily["allowed_history"]).sum()),
            "raw_rows": int(daily.loc[~daily["allowed_history"], "raw_rows"].sum()),
            "successful_boardings": int(
                daily.loc[~daily["allowed_history"], "successful_boardings"].sum()
            ),
            "used_for_modeling": False,
        },
        "route_values": dict(route_values.most_common()),
        "unparseable_route_values": dict(invalid_route_values.most_common()),
        "combined_13_50_values": {
            value: count
            for value, count in route_values.items()
            if "13" in value and "50" in value
        },
        "outputs": {
            "daily": "route-day-raw-coverage.csv",
            "monthly": "route-month-daytype.csv",
            "focus": "focus-route-days.csv",
        },
        "interpretation_limit": (
            "Device/vehicle/run coverage is diagnostic only. Low observed coverage is not "
            "proof of a data defect or permission to replace organizer target values."
        ),
    }
    (args.output_dir / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_serialise) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output_dir), "processed_rows": processed_rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
