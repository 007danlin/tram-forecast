"""Compact deterministic hourly model and recursive multi-step inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.data import full_hourly_grid
from ml.settings import RANDOM_SEED, ROUTES, TARGET_COLUMN


LAG_DAYS = (7, 14, 21, 28)
LAG_COLUMNS = tuple(f"lag_{days}d" for days in LAG_DAYS)
CATEGORICAL_COLUMNS = ("route", "hour", "dow", "month")
CALENDAR_NUMERIC_COLUMNS = ("is_weekend", "day_of_year_sin", "day_of_year_cos")
LAG_NUMERIC_COLUMNS = (*LAG_COLUMNS, "lag_mean_4w", "lag_median_4w", "recent_trend")
HGBT_FIXED_PARAMETERS = {
    "loss": "absolute_error",
    "learning_rate": 0.08,
    "min_samples_leaf": 24,
    "l2_regularization": 1.0,
}


def _calendar_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["dow"] = result["date"].dt.dayofweek.astype("int8")
    result["month"] = result["date"].dt.month.astype("int8")
    result["is_weekend"] = (result["dow"] >= 5).astype("int8")
    day_of_year = result["date"].dt.dayofyear.to_numpy(dtype=float)
    result["day_of_year_sin"] = np.sin(2.0 * np.pi * day_of_year / 365.25)
    result["day_of_year_cos"] = np.cos(2.0 * np.pi * day_of_year / 365.25)
    return result


def make_training_features(history: pd.DataFrame, *, include_lags: bool) -> tuple[pd.DataFrame, np.ndarray]:
    data = _calendar_features(history.sort_values(["route", "timestamp"], ignore_index=True))
    if include_lags:
        grouped = data.groupby("route", sort=False)[TARGET_COLUMN]
        for days, column in zip(LAG_DAYS, LAG_COLUMNS):
            data[column] = grouped.shift(days * 24)
        data["lag_mean_4w"] = data[list(LAG_COLUMNS)].mean(axis=1)
        data["lag_median_4w"] = data[list(LAG_COLUMNS)].median(axis=1)
        denominator = data[["lag_14d", "lag_21d", "lag_28d"]].mean(axis=1).clip(lower=1.0)
        data["recent_trend"] = (data["lag_7d"] / denominator).clip(0.0, 3.0)
        data = data.dropna(subset=list(LAG_COLUMNS))
    columns = [*CATEGORICAL_COLUMNS, *CALENDAR_NUMERIC_COLUMNS]
    if include_lags:
        columns.extend(LAG_NUMERIC_COLUMNS)
    return data[columns], data[TARGET_COLUMN].to_numpy(dtype=float)


def _pipeline(numeric_columns: tuple[str, ...], *, max_iter: int, max_leaf_nodes: int) -> Pipeline:
    preprocessing = ColumnTransformer(
        [
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), list(CATEGORICAL_COLUMNS)),
            ("numeric", StandardScaler(), list(numeric_columns)),
        ],
        remainder="drop",
    )
    regressor = HistGradientBoostingRegressor(
        **HGBT_FIXED_PARAMETERS,
        max_iter=max_iter,
        max_leaf_nodes=max_leaf_nodes,
        random_state=RANDOM_SEED,
    )
    return Pipeline([("preprocessing", preprocessing), ("regressor", regressor)])


@dataclass
class HourlyGradientBoostingModel:
    """Calendar model with an optional leakage-safe recursive weekly-lag mode."""

    include_lags: bool = True
    max_iter: int = 220
    max_leaf_nodes: int = 31

    @property
    def name(self) -> str:
        return "lagged_hgbt" if self.include_lags else "calendar_hgbt"

    def fit(self, history: pd.DataFrame) -> "HourlyGradientBoostingModel":
        ordered = history.sort_values(["route", "timestamp"], ignore_index=True).copy()
        route_totals = ordered.groupby("route")[TARGET_COLUMN].sum()
        self.supported_routes_ = tuple(sorted(route_totals[route_totals > 0].index.astype(int)))
        training = ordered[ordered["route"].isin(self.supported_routes_)].copy()
        features, target = make_training_features(training, include_lags=self.include_lags)
        numeric = CALENDAR_NUMERIC_COLUMNS + (LAG_NUMERIC_COLUMNS if self.include_lags else ())
        self.pipeline_ = _pipeline(numeric, max_iter=self.max_iter, max_leaf_nodes=self.max_leaf_nodes)
        self.pipeline_.fit(features, target)
        self.history_ = ordered[["route", "date", "hour", "timestamp", TARGET_COLUMN]].copy()
        self.history_start_ = ordered["date"].min()
        self.history_end_ = ordered["date"].max()
        return self

    def _future_features(self, frame: pd.DataFrame, values: dict[tuple[int, pd.Timestamp], float]) -> pd.DataFrame:
        result = _calendar_features(frame)
        if self.include_lags:
            for days, column in zip(LAG_DAYS, LAG_COLUMNS):
                result[column] = [values.get((int(r), ts - pd.Timedelta(days=days)), np.nan) for r, ts in zip(result.route, result.timestamp)]
            if result[list(LAG_COLUMNS)].isna().any().any():
                raise ValueError("Insufficient history for recursive weekly-lag prediction")
            result["lag_mean_4w"] = result[list(LAG_COLUMNS)].mean(axis=1)
            result["lag_median_4w"] = result[list(LAG_COLUMNS)].median(axis=1)
            denominator = result[["lag_14d", "lag_21d", "lag_28d"]].mean(axis=1).clip(lower=1.0)
            result["recent_trend"] = (result["lag_7d"] / denominator).clip(0.0, 3.0)
        columns = [*CATEGORICAL_COLUMNS, *CALENDAR_NUMERIC_COLUMNS]
        if self.include_lags:
            columns.extend(LAG_NUMERIC_COLUMNS)
        return result[columns]

    def predict(self, start: date | str, end: date | str) -> pd.DataFrame:
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        if start_ts <= self.history_end_:
            raise ValueError("Prediction start must be after the fitted history")

        grid = full_hourly_grid(start_ts, end_ts, ROUTES)
        grid["timestamp"] = grid["date"] + pd.to_timedelta(grid["hour"], unit="h")
        values = {
            (int(row.route), row.timestamp): float(row.boardings)
            for row in self.history_.itertuples(index=False)
            if int(row.route) in self.supported_routes_
        }
        daily_results: list[pd.DataFrame] = []
        for prediction_date in pd.date_range(start_ts, end_ts, freq="D"):
            batch = grid[(grid["date"] == prediction_date) & grid["route"].isin(self.supported_routes_)].copy()
            features = self._future_features(batch, values)
            batch["prediction"] = np.maximum(self.pipeline_.predict(features), 0.0)
            for row in batch.itertuples(index=False):
                values[(int(row.route), row.timestamp)] = float(row.prediction)
            daily_results.append(batch)

        predicted = pd.concat(daily_results, ignore_index=True) if daily_results else grid.iloc[0:0].copy()
        result = grid.merge(predicted[["route", "date", "hour", "prediction"]], on=["route", "date", "hour"], how="left")
        result["status"] = np.where(result["route"].isin(self.supported_routes_), "ok", "cold_start_zero_baseline")
        result["prediction"] = result["prediction"].fillna(0.0).clip(lower=0.0)
        return result
