"""Confirmed organizer data contract and temporal evaluation settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


# The unpacked organizer sample still contains ten routes. A later Q&A addendum
# excludes route 5 from the trained model scope. Keep these concepts separate:
# transport/export compatibility must not silently redefine model applicability.
SAMPLE_ROUTES = (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)
MODELED_ROUTES = (1, 7, 11, 12, 17, 25, 26, 28, 50)
ROUTES = SAMPLE_ROUTES  # Backward-compatible name for existing transport grids.
TARGET_COLUMN = "boardings"
KEY_COLUMNS = ("route", "date", "hour")
RAW_TIMESTAMP_COLUMN = "tran_date_time"
SUCCESS_VALIDATION_RESULT = "1"
MODEL_SCHEMA_VERSION = "tramflow-hourly-v1"
RANDOM_SEED = 20250925


@dataclass(frozen=True)
class TemporalFold:
    """Expanding-window fold with half-open conceptual availability at val_start."""

    name: str
    train_start: date
    train_end: date
    val_start: date
    val_end: date
    role: str


SELECTION_FOLDS = (
    TemporalFold(
        name="selection_2025_may_jun",
        train_start=date(2025, 1, 1),
        train_end=date(2025, 4, 30),
        val_start=date(2025, 5, 1),
        val_end=date(2025, 6, 30),
        role="model_selection",
    ),
    TemporalFold(
        name="selection_2025_jul_aug",
        train_start=date(2025, 1, 1),
        train_end=date(2025, 6, 30),
        val_start=date(2025, 7, 1),
        val_end=date(2025, 8, 31),
        role="model_selection",
    ),
)

FINAL_VALIDATION = TemporalFold(
    name="reused_validation_2025_sep_oct",
    train_start=date(2025, 1, 1),
    train_end=date(2025, 8, 31),
    val_start=date(2025, 9, 1),
    val_end=date(2025, 10, 31),
    role="reused_final_validation",
)

# Compatibility alias for earlier local reports. The period is not a pristine holdout:
# it was already evaluated in PR #2 before the addendum experiments.
FINAL_HOLDOUT = FINAL_VALIDATION

FINAL_TRAIN_START = date(2025, 1, 1)
FINAL_TRAIN_END = date(2025, 10, 31)
FORECAST_START = date(2025, 11, 1)
FORECAST_END = date(2025, 12, 31)
