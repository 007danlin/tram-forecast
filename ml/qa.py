"""QA helpers for route scope, training masks, and unexplained history drops."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from ml.settings import KEY_COLUMNS, MODELED_ROUTES, TARGET_COLUMN


TRAINING_MASK_SCHEMA_VERSION = "tramflow-training-mask-v1"
MASK_TIMESTAMP_BASIS = "organizer_tran_date_time_naive"
REQUIRED_RULE_FIELDS = {
    "rule_id",
    "route",
    "start",
    "end",
    "reason_code",
    "source_ref",
    "verification_status",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_training_mask(path: str | Path) -> dict[str, object]:
    """Load a verified, hour-aligned training mask without guessing service hours."""
    source = Path(path)
    document = json.loads(source.read_text(encoding="utf-8"))
    if document.get("schema_version") != TRAINING_MASK_SCHEMA_VERSION:
        raise ValueError("Unsupported training-mask schema")
    if not isinstance(document.get("mask_id"), str) or not document["mask_id"].strip():
        raise ValueError("Training mask requires a non-empty mask_id")
    if document.get("timestamp_basis") != MASK_TIMESTAMP_BASIS:
        raise ValueError("Training mask must use the organizer tran_date_time basis")
    timezone = document.get("timezone")
    if not isinstance(timezone, str) or not timezone.strip():
        raise ValueError("Training mask must state its timezone or unresolved timezone status")
    rules = document.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Training mask requires at least one verified rule")

    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for raw_rule in rules:
        if not isinstance(raw_rule, dict) or set(raw_rule) != REQUIRED_RULE_FIELDS:
            raise ValueError(f"Training-mask rule fields must be exactly {sorted(REQUIRED_RULE_FIELDS)}")
        rule_id = raw_rule["rule_id"]
        if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in seen_ids:
            raise ValueError("Training-mask rule_id values must be unique non-empty strings")
        seen_ids.add(rule_id)
        route = int(raw_rule["route"])
        if route not in MODELED_ROUTES:
            raise ValueError(f"Training-mask route is outside the nine-route model scope: {route}")
        if raw_rule["verification_status"] != "verified":
            raise ValueError(f"Training-mask rule is not verified: {rule_id}")
        if not str(raw_rule["source_ref"]).strip() or not str(raw_rule["reason_code"]).strip():
            raise ValueError(f"Training-mask rule lacks source/reason: {rule_id}")
        start = pd.to_datetime(raw_rule["start"], format="%Y-%m-%d %H:%M:%S", errors="raise")
        end = pd.to_datetime(raw_rule["end"], format="%Y-%m-%d %H:%M:%S", errors="raise")
        if start.tzinfo is not None or end.tzinfo is not None:
            raise ValueError("Mask timestamps must match the organizer's naive tran_date_time values")
        if end <= start:
            raise ValueError(f"Training-mask rule has an empty or reversed interval: {rule_id}")
        if any((start.minute, start.second, start.microsecond, end.minute, end.second, end.microsecond)):
            raise ValueError(
                f"Training-mask rule is not hour-aligned: {rule_id}; partial hours require event-level target rebuilding"
            )
        normalized.append({**raw_rule, "route": route, "start": start, "end": end})

    ordered = sorted(normalized, key=lambda item: (item["route"], item["start"], item["end"]))
    for previous, current in zip(ordered, ordered[1:]):
        if previous["route"] == current["route"] and current["start"] < previous["end"]:
            raise ValueError(
                f"Overlapping training-mask rules for route {current['route']}: "
                f"{previous['rule_id']} and {current['rule_id']}"
            )
    return {
        **document,
        "rules": ordered,
        "source_file": str(source),
        "sha256": sha256_file(source),
    }


def apply_training_mask(frame: pd.DataFrame, mask: dict[str, object]) -> pd.DataFrame:
    """Mark full route-hour rows as excluded while preserving their original target."""
    required = {*KEY_COLUMNS, "timestamp", TARGET_COLUMN}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Training frame misses mask columns: {sorted(missing)}")
    result = frame.copy()
    result["training_included"] = True
    result["training_mask_rule_id"] = pd.NA
    for rule in mask["rules"]:
        selected = (
            result["route"].eq(rule["route"])
            & result["timestamp"].ge(rule["start"])
            & result["timestamp"].lt(rule["end"])
        )
        result.loc[selected, "training_included"] = False
        result.loc[selected, "training_mask_rule_id"] = rule["rule_id"]
    return result


def training_mask_summary(frame: pd.DataFrame, mask: dict[str, object]) -> dict[str, object]:
    marked = apply_training_mask(frame, mask)
    excluded = marked[~marked["training_included"]]
    by_route = (
        excluded.groupby("route", sort=True)
        .agg(excluded_hours=(TARGET_COLUMN, "size"), excluded_boardings=(TARGET_COLUMN, "sum"))
        .reset_index()
    )
    return {
        "mask_id": mask["mask_id"],
        "mask_sha256": mask["sha256"],
        "timestamp_basis": mask["timestamp_basis"],
        "timezone": mask["timezone"],
        "original_rows": int(len(marked)),
        "excluded_hours": int(len(excluded)),
        "original_target_sum": int(marked[TARGET_COLUMN].sum()),
        "excluded_target_sum": int(excluded[TARGET_COLUMN].sum()),
        "cleaned_target_sum": int(marked.loc[marked["training_included"], TARGET_COLUMN].sum()),
        "by_route": by_route.to_dict(orient="records"),
    }


def history_drop_candidates(
    frame: pd.DataFrame,
    *,
    routes: Sequence[int] = MODELED_ROUTES,
    lookback_weeks: int = 4,
    ratio_threshold: float = 0.10,
    minimum_baseline: float = 100.0,
) -> pd.DataFrame:
    """Flag large daily drops without assigning a cause or changing the target."""
    data = frame[frame["route"].isin(routes)].copy()
    daily = (
        data.groupby(["route", "date"], as_index=False)[TARGET_COLUMN]
        .sum()
        .sort_values(["route", "date"], ignore_index=True)
    )
    daily["weekday"] = daily["date"].dt.dayofweek
    daily["reference_median"] = daily.groupby(["route", "weekday"])[TARGET_COLUMN].transform(
        lambda values: values.shift().rolling(lookback_weeks, min_periods=lookback_weeks).median()
    )
    daily["ratio_to_reference"] = daily[TARGET_COLUMN] / daily["reference_median"].replace(0, pd.NA)
    selected = daily[
        daily["reference_median"].ge(minimum_baseline)
        & daily["ratio_to_reference"].le(ratio_threshold)
    ].copy()
    selected["cause_status"] = "unknown_unverified"
    selected["recovery_applied"] = False
    return selected[
        [
            "route",
            "date",
            TARGET_COLUMN,
            "reference_median",
            "ratio_to_reference",
            "cause_status",
            "recovery_applied",
        ]
    ].sort_values(["ratio_to_reference", "route", "date"], ignore_index=True)
