"""Read and validate organizer labels or rebuild them from raw CSV in chunks."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from ml.settings import KEY_COLUMNS, ROUTES, SUCCESS_VALIDATION_RESULT, TARGET_COLUMN


LABEL_COLUMNS = [*KEY_COLUMNS, TARGET_COLUMN]
RAW_REQUIRED_COLUMNS = ["tran_date_time", "validation_result", "ngpt_route"]


class DataContractError(ValueError):
    """The supplied organizer files do not satisfy the audited contract."""


def _as_timestamp(value: date | str | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def full_hourly_grid(
    start: date | str | pd.Timestamp,
    end: date | str | pd.Timestamp,
    routes: Sequence[int] = ROUTES,
) -> pd.DataFrame:
    start_ts = _as_timestamp(start)
    end_ts = _as_timestamp(end)
    if end_ts < start_ts:
        raise ValueError("end must not precede start")
    index = pd.MultiIndex.from_product(
        [tuple(routes), pd.date_range(start_ts, end_ts, freq="D"), range(24)],
        names=list(KEY_COLUMNS),
    )
    return index.to_frame(index=False)


def validate_target_rows(frame: pd.DataFrame, *, allow_partial_grid: bool = True) -> None:
    missing_columns = set(LABEL_COLUMNS) - set(frame.columns)
    if missing_columns:
        raise DataContractError(f"Missing target columns: {sorted(missing_columns)}")
    if frame[LABEL_COLUMNS].isna().any().any():
        raise DataContractError("Target rows contain null key or target values")
    if frame.duplicated(list(KEY_COLUMNS)).any():
        raise DataContractError("Duplicate route/date/hour target keys")
    if not frame["hour"].between(0, 23).all():
        raise DataContractError("hour must be between 0 and 23")
    if (frame[TARGET_COLUMN] < 0).any():
        raise DataContractError("boardings must be nonnegative")
    if not allow_partial_grid and len(frame) == 0:
        raise DataContractError("Target grid is empty")


def load_organizer_labels(
    dataset_dir: str | Path,
    start: date | str | pd.Timestamp,
    end: date | str | pd.Timestamp,
    *,
    routes: Sequence[int] = ROUTES,
) -> pd.DataFrame:
    """Load audited label files and expand absent count cells to explicit zeros."""
    root = Path(dataset_dir)
    paths = [root / "labels" / "labels_day_train.csv", root / "labels" / "labels_day_test.csv"]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing organizer labels: {missing}")

    parts = [pd.read_csv(path, sep=";", dtype={"route": "int64", "hour": "int64", "boardings": "int64"}) for path in paths]
    labels = pd.concat(parts, ignore_index=True)
    labels["date"] = pd.to_datetime(labels["date"], format="%Y-%m-%d", errors="raise")
    validate_target_rows(labels)

    start_ts = _as_timestamp(start)
    end_ts = _as_timestamp(end)
    labels = labels[labels["date"].between(start_ts, end_ts)].copy()
    unexpected_routes = sorted(set(labels["route"]) - set(routes))
    if unexpected_routes:
        raise DataContractError(f"Unexpected routes in labels: {unexpected_routes}")

    grid = full_hourly_grid(start_ts, end_ts, routes)
    result = grid.merge(labels, on=list(KEY_COLUMNS), how="left", validate="one_to_one")
    result["has_positive_label_row"] = result[TARGET_COLUMN].notna()
    result[TARGET_COLUMN] = result[TARGET_COLUMN].fillna(0).astype("int64")
    result["timestamp"] = result["date"] + pd.to_timedelta(result["hour"], unit="h")
    result = result.sort_values(["route", "timestamp"], ignore_index=True)
    validate_target_rows(result)
    return result


def build_target_from_raw(
    raw_paths: Iterable[str | Path],
    start: date | str | pd.Timestamp,
    end: date | str | pd.Timestamp,
    *,
    routes: Sequence[int] = ROUTES,
    chunksize: int = 500_000,
) -> pd.DataFrame:
    """Rebuild target without loading either multi-gigabyte raw file into memory."""
    start_ts = _as_timestamp(start)
    end_exclusive = _as_timestamp(end) + pd.Timedelta(days=1)
    aggregates: list[pd.DataFrame] = []

    for raw_path in (Path(path) for path in raw_paths):
        if not raw_path.is_file():
            raise FileNotFoundError(raw_path)
        reader = pd.read_csv(
            raw_path,
            sep=";",
            usecols=RAW_REQUIRED_COLUMNS,
            dtype="string",
            chunksize=chunksize,
        )
        for chunk in reader:
            timestamp = pd.to_datetime(chunk["tran_date_time"], format="%Y-%m-%d %H:%M:%S", errors="raise")
            mask = (
                chunk["validation_result"].eq(SUCCESS_VALIDATION_RESULT)
                & timestamp.ge(start_ts)
                & timestamp.lt(end_exclusive)
            )
            if not mask.any():
                continue
            selected = chunk.loc[mask, ["ngpt_route"]].copy()
            selected["timestamp"] = timestamp.loc[mask]
            route_text = selected["ngpt_route"].str.extract(r"^(\d+)\s+трамвай$", expand=False)
            if route_text.isna().any():
                examples = selected.loc[route_text.isna(), "ngpt_route"].drop_duplicates().head(5).tolist()
                raise DataContractError(f"Unparseable successful ngpt_route values: {examples}")
            selected["route"] = route_text.astype("int64")
            selected["date"] = selected["timestamp"].dt.normalize()
            selected["hour"] = selected["timestamp"].dt.hour.astype("int64")
            grouped = selected.groupby(list(KEY_COLUMNS), as_index=False).size().rename(columns={"size": TARGET_COLUMN})
            aggregates.append(grouped)

    if aggregates:
        positive = (
            pd.concat(aggregates, ignore_index=True)
            .groupby(list(KEY_COLUMNS), as_index=False)[TARGET_COLUMN]
            .sum()
        )
    else:
        positive = pd.DataFrame(columns=LABEL_COLUMNS)

    unexpected_routes = sorted(set(positive.get("route", pd.Series(dtype=int))) - set(routes))
    if unexpected_routes:
        raise DataContractError(f"Unexpected routes in raw target: {unexpected_routes}")
    grid = full_hourly_grid(start_ts, end_exclusive - pd.Timedelta(days=1), routes)
    result = grid.merge(positive, on=list(KEY_COLUMNS), how="left", validate="one_to_one")
    result["has_positive_label_row"] = result[TARGET_COLUMN].notna()
    result[TARGET_COLUMN] = result[TARGET_COLUMN].fillna(0).astype("int64")
    result["timestamp"] = result["date"] + pd.to_timedelta(result["hour"], unit="h")
    result = result.sort_values(["route", "timestamp"], ignore_index=True)
    validate_target_rows(result)
    return result
