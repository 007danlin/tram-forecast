"""Evaluation metrics with explicit zero-demand semantics."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def round_submission_predictions(values: Iterable[float]) -> np.ndarray:
    """Apply the exact integer export policy used by the organizer submission."""
    predicted = np.asarray(tuple(values), dtype=float)
    if predicted.ndim != 1:
        raise ValueError("Submission rounding requires one-dimensional inputs")
    if not np.isfinite(predicted).all() or (predicted < 0).any():
        raise ValueError("Submission rounding requires finite nonnegative values")
    return np.floor(predicted + 0.5).astype("int64")


def regression_metrics(y_true: Iterable[float], y_pred: Iterable[float]) -> dict[str, float | int | None]:
    """Return organizer WAPE metrics without inventing a zero-denominator score."""
    actual = np.asarray(tuple(y_true), dtype=float)
    predicted = np.asarray(tuple(y_pred), dtype=float)
    if actual.shape != predicted.shape:
        raise ValueError(f"Shape mismatch: actual={actual.shape}, predicted={predicted.shape}")
    if actual.ndim != 1:
        raise ValueError("Metrics require one-dimensional inputs")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metrics do not accept NaN or infinite values")
    if (actual < 0).any() or (predicted < 0).any():
        raise ValueError("Passenger-flow values must be nonnegative")

    absolute_error = np.abs(actual - predicted)
    denominator = float(actual.sum())
    mae = float(absolute_error.mean()) if len(actual) else None
    if denominator == 0:
        wape = None
        score = None
    else:
        wape = float(absolute_error.sum() / denominator)
        score = float(max(0.0, 1.0 - wape))
    return {
        "rows": int(len(actual)),
        "sum_y": denominator,
        "sum_abs_error": float(absolute_error.sum()),
        "mae": mae,
        "wape": wape,
        "wape_score": score,
    }
