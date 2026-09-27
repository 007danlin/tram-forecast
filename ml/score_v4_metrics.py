"""Submission-consistent v4 diagnostics; historical v3 reports stay unchanged."""

import numpy as np
import pandas as pd

from ml.factors import add_official_calendar_features
from ml.score_improvement import metrics
from ml.score_v3_study import summarize_v3
from ml.score_v4 import official_day_type
from ml.settings import TARGET_COLUMN


def summarize_v4(frame: pd.DataFrame) -> dict:
    summary = summarize_v3(frame)
    data = frame.copy()
    data["rounded_prediction"] = np.floor(np.maximum(data.prediction.to_numpy(float), 0) + .5)
    data["hourly_ae"] = np.abs(data[TARGET_COLUMN] - data.rounded_prediction)
    daily = data.groupby(["fold", "route", "date"], as_index=False).agg(
        y=(TARGET_COLUMN, "sum"), prediction=("rounded_prediction", "sum"),
        hourly_sae=("hourly_ae", "sum"),
    )
    daily_ae = np.abs(daily.y - daily.prediction)
    hourly_sae = float(data.hourly_ae.sum())
    daily_sae = float(daily_ae.sum())
    total = float(data[TARGET_COLUMN].sum())
    low = daily.y.le(1000)
    summary["daily"] = {
        "rounding": "sum of floor(max(hourly_prediction, 0) + 0.5)",
        "absolute_error": daily_sae,
        "score": max(0.0, 1.0 - daily_sae / total) if total else None,
        "hourly_absolute_error": hourly_sae,
        "level_error_share_of_hourly_sae": daily_sae / hourly_sae if hourly_sae else None,
        "within_day_opposing_errors": hourly_sae - daily_sae,
        "decomposition_caveat": "Cancellation diagnostic; not a causal or independently achievable shape gain.",
        "signed_bias": float((daily.prediction - daily.y).sum()),
        "low_volume_threshold": 1000,
        "low_volume_days": int(low.sum()),
        "low_volume_absolute_error": float(daily_ae[low].sum()),
    }
    calendar = add_official_calendar_features(data)
    data["official_day_type"] = official_day_type(data)
    data.loc[calendar.is_working_weekend.eq(1), "official_day_type"] = "working_saturday"
    summary["slices"]["official_day_type"] = {
        str(key): metrics(group) for key, group in data.groupby("official_day_type", sort=True)
    }
    return summary
