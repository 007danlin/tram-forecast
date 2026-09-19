"""Deterministic synthetic data for checking integration only."""
from datetime import datetime, timedelta, timezone


def predict_mock() -> dict:
    """No inputs or I/O. Return a fresh mock series, never a real prediction."""
    start = datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=3)))
    return {
        "is_mock": True,
        "unit": "passengers",
        "points": [
            {"timestamp": (start + timedelta(minutes=15 * i)).isoformat(), "value": value}
            for i, value in enumerate((12, 18, 15, 24, 21, 16))
        ],
    }
