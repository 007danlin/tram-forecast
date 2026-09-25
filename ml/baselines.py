"""Deterministic temporal baselines using facts available at fit time only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ml.data import full_hourly_grid
from ml.settings import ROUTES, TARGET_COLUMN


def _prediction_grid(start: date | str, end: date | str) -> pd.DataFrame:
    frame = full_hourly_grid(start, end, ROUTES)
    frame["timestamp"] = frame["date"] + pd.to_timedelta(frame["hour"], unit="h")
    frame["dow"] = frame["date"].dt.dayofweek.astype("int8")
    return frame


@dataclass
class BlockMeanBaseline:
    """Reproducible equivalent of the supplied three-eight-hour-block baseline."""

    name: str = "block_mean"

    def fit(self, history: pd.DataFrame) -> "BlockMeanBaseline":
        data = history.copy()
        data["block"] = data["hour"] // 8
        self.supported_routes_ = tuple(sorted(data.groupby("route")[TARGET_COLUMN].sum().loc[lambda x: x > 0].index))
        self.lookup_ = data.groupby(["route", "block"])[TARGET_COLUMN].mean().to_dict()
        return self

    def predict(self, start: date | str, end: date | str) -> pd.DataFrame:
        frame = _prediction_grid(start, end)
        frame["prediction"] = [float(self.lookup_.get((route, hour // 8), 0.0)) for route, hour in zip(frame.route, frame.hour)]
        frame["status"] = np.where(frame["route"].isin(self.supported_routes_), "ok", "cold_start_zero_baseline")
        return frame


@dataclass
class PreviousWeekdayBaseline:
    """Use the latest available value for the same route, hour and weekday."""

    name: str = "previous_weekday"

    def fit(self, history: pd.DataFrame) -> "PreviousWeekdayBaseline":
        data = history.copy()
        data["dow"] = data["date"].dt.dayofweek
        data = data.sort_values("timestamp")
        self.supported_routes_ = tuple(sorted(data.groupby("route")[TARGET_COLUMN].sum().loc[lambda x: x > 0].index))
        self.lookup_ = data.groupby(["route", "hour", "dow"], sort=False)[TARGET_COLUMN].last().to_dict()
        self.fallback_ = data.groupby(["route", "hour"])[TARGET_COLUMN].median().to_dict()
        return self

    def predict(self, start: date | str, end: date | str) -> pd.DataFrame:
        frame = _prediction_grid(start, end)
        frame["prediction"] = [
            float(self.lookup_.get((r, h, d), self.fallback_.get((r, h), 0.0)))
            for r, h, d in zip(frame.route, frame.hour, frame.dow)
        ]
        frame["status"] = np.where(frame["route"].isin(self.supported_routes_), "ok", "cold_start_zero_baseline")
        return frame


@dataclass
class ComparableWeeksMedianBaseline:
    """Median of the most recent comparable weekdays, route by route and hour by hour."""

    weeks: int = 8
    name: str = "median_comparable_weeks"

    def fit(self, history: pd.DataFrame) -> "ComparableWeeksMedianBaseline":
        data = history.copy().sort_values("timestamp")
        data["dow"] = data["date"].dt.dayofweek
        self.supported_routes_ = tuple(sorted(data.groupby("route")[TARGET_COLUMN].sum().loc[lambda x: x > 0].index))
        recent = data.groupby(["route", "hour", "dow"], group_keys=False).tail(self.weeks)
        self.lookup_ = recent.groupby(["route", "hour", "dow"])[TARGET_COLUMN].median().to_dict()
        self.fallback_ = data.groupby(["route", "hour"])[TARGET_COLUMN].median().to_dict()
        return self

    def predict(self, start: date | str, end: date | str) -> pd.DataFrame:
        frame = _prediction_grid(start, end)
        frame["prediction"] = [
            float(self.lookup_.get((r, h, d), self.fallback_.get((r, h), 0.0)))
            for r, h, d in zip(frame.route, frame.hour, frame.dow)
        ]
        frame["status"] = np.where(frame["route"].isin(self.supported_routes_), "ok", "cold_start_zero_baseline")
        return frame
