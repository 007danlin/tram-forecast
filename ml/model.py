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
from ml.experiment_config import normalize_config
from ml.factors import (
    HOLIDAY_MODEL_COLUMNS,
    WEATHER_MODEL_COLUMNS,
    add_official_calendar_features,
)
from ml.settings import MODELED_ROUTES, RANDOM_SEED, ROUTES, TARGET_COLUMN


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

INTERACTION_CATEGORICAL_COLUMNS = (
    "route_code",
    "hour",
    "dow",
    "month",
    "route_hour",
    "route_dow",
    "hour_dow",
    "week",
)
INTERACTION_NUMERIC_COLUMNS = (*HOLIDAY_MODEL_COLUMNS, "day_of_year_sin", "day_of_year_cos")
INTERACTION_HALF_LIFE_DAYS = 90.0
ENSEMBLE_CALENDAR_WEIGHT = 0.425
ENSEMBLE_INTERACTION_WEIGHT = 0.575
ENSEMBLE_SCALE = 0.96


def build_hgbt_model(model_name: str, experiment_config: dict | None = None) -> "HourlyGradientBoostingModel":
    if model_name == "calendar_interaction_squared_hgbt":
        if experiment_config is not None:
            raise ValueError("Interaction model does not accept a weather experiment config")
        return NativeInteractionGradientBoostingModel()
    if model_name == "calendar_interaction_ensemble":
        if experiment_config is not None:
            raise ValueError("Interaction ensemble does not accept a weather experiment config")
        return CalendarInteractionEnsembleModel()

    if model_name.startswith("score_"):
        from ml.score_models import ScoreModel
        model = ScoreModel(experiment_config)
        if model.name != model_name:
            raise ValueError("Model name and score config disagree")
        return model
    variants = {
        "calendar_hgbt": dict(include_lags=False),
        "lagged_hgbt": dict(include_lags=True),
        "calendar_holiday_hgbt": dict(
            include_lags=False,
            include_official_calendar=True,
            information_mode="operational",
        ),
        "competition_weather_hgbt": dict(
            include_lags=False,
            include_official_calendar=True,
            include_weather=True,
            information_mode="competition_retro",
        ),
    }
    if model_name not in variants:
        raise ValueError(f"Unknown gradient-boosting model variant: {model_name}")
    options = variants[model_name].copy()
    if experiment_config is not None:
        config = normalize_config(experiment_config)
        if model_name != config["model_name"]:
            raise ValueError("Model name and experiment config disagree")
        options.update(weather_columns=tuple(config["weather_columns"]), experiment_config=config)
        if "seed" in config:
            options["random_seed"] = config["seed"]
    return HourlyGradientBoostingModel(**options)


def _calendar_features(frame: pd.DataFrame, *, include_official_calendar: bool = False) -> pd.DataFrame:
    result = frame.copy()
    result["dow"] = result["date"].dt.dayofweek.astype("int8")
    result["month"] = result["date"].dt.month.astype("int8")
    result["is_weekend"] = (result["dow"] >= 5).astype("int8")
    day_of_year = result["date"].dt.dayofyear.to_numpy(dtype=float)
    result["day_of_year_sin"] = np.sin(2.0 * np.pi * day_of_year / 365.25)
    result["day_of_year_cos"] = np.cos(2.0 * np.pi * day_of_year / 365.25)
    if include_official_calendar:
        result = add_official_calendar_features(result)
    return result


def _interaction_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Calendar interactions with bounded native-categorical codes."""
    result = add_official_calendar_features(frame[["route", "date", "hour"]].copy())
    route_codes = {route: index for index, route in enumerate(MODELED_ROUTES)}
    if not result["route"].isin(route_codes).all():
        unsupported = sorted(result.loc[~result["route"].isin(route_codes), "route"].unique().tolist())
        raise ValueError(f"Interaction features received unsupported routes: {unsupported}")
    result["route_code"] = result["route"].map(route_codes).astype("int16")
    result["dow"] = result["date"].dt.dayofweek.astype("int8")
    result["month"] = (result["date"].dt.month - 1).astype("int8")
    result["week"] = (result["date"].dt.isocalendar().week.astype(int) - 1).astype("int16")
    result["route_hour"] = (result["route_code"] * 24 + result["hour"]).astype("int16")
    result["route_dow"] = (result["route_code"] * 7 + result["dow"]).astype("int16")
    result["hour_dow"] = (result["dow"] * 24 + result["hour"]).astype("int16")
    day_of_year = result["date"].dt.dayofyear.to_numpy(dtype=float)
    result["day_of_year_sin"] = np.sin(2.0 * np.pi * day_of_year / 365.25)
    result["day_of_year_cos"] = np.cos(2.0 * np.pi * day_of_year / 365.25)
    return result[[*INTERACTION_CATEGORICAL_COLUMNS, *INTERACTION_NUMERIC_COLUMNS]]


def _attach_weather(frame: pd.DataFrame, factors: pd.DataFrame | None, weather_columns=WEATHER_MODEL_COLUMNS) -> pd.DataFrame:
    if factors is None:
        raise ValueError("Weather factors are required for this model variant")
    columns = ["timestamp", *weather_columns]
    missing = set(columns) - set(factors.columns)
    if missing:
        raise ValueError(f"Weather factors miss required columns: {sorted(missing)}")
    result = frame.merge(factors[columns], on="timestamp", how="left", validate="many_to_one")
    if result[list(weather_columns)].isna().any().any():
        first_missing = result.loc[result[list(weather_columns)].isna().any(axis=1), "timestamp"].min()
        raise ValueError(f"Weather factors do not cover model rows from {first_missing}")
    if len(result) != len(frame) or not np.isfinite(result[list(weather_columns)].to_numpy(dtype=float)).all():
        raise ValueError("Weather join changed rows or contains non-finite values")
    return result


def make_training_features(
    history: pd.DataFrame,
    *,
    include_lags: bool,
    include_official_calendar: bool = False,
    include_weather: bool = False,
    factors: pd.DataFrame | None = None,
    weather_columns: tuple[str, ...] = WEATHER_MODEL_COLUMNS,
) -> tuple[pd.DataFrame, np.ndarray]:
    data = _calendar_features(
        history.sort_values(["route", "timestamp"], ignore_index=True),
        include_official_calendar=include_official_calendar,
    )
    if include_weather:
        data = _attach_weather(data, factors, weather_columns)
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
    if include_official_calendar:
        columns.extend(HOLIDAY_MODEL_COLUMNS)
    if include_weather:
        columns.extend(weather_columns)
    if include_lags:
        columns.extend(LAG_NUMERIC_COLUMNS)
    return data[columns], data[TARGET_COLUMN].to_numpy(dtype=float)


def _pipeline(numeric_columns: tuple[str, ...], *, max_iter: int, max_leaf_nodes: int, random_seed: int = RANDOM_SEED) -> Pipeline:
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
        random_state=random_seed,
    )
    return Pipeline([("preprocessing", preprocessing), ("regressor", regressor)])


@dataclass
class HourlyGradientBoostingModel:
    """Calendar model with an optional leakage-safe recursive weekly-lag mode."""

    include_lags: bool = True
    include_official_calendar: bool = False
    include_weather: bool = False
    information_mode: str = "operational"
    weather_columns: tuple[str, ...] | None = None
    experiment_config: dict | None = None
    max_iter: int = 220
    max_leaf_nodes: int = 31
    random_seed: int = RANDOM_SEED

    @property
    def selected_weather_columns(self):
        # getattr keeps older joblib instances (without the new field) readable.
        columns = getattr(self, "weather_columns", None)
        return WEATHER_MODEL_COLUMNS if columns is None else columns

    @property
    def name(self) -> str:
        if self.include_weather:
            return "competition_weather_hgbt"
        if self.include_official_calendar:
            return "calendar_holiday_hgbt"
        return "lagged_hgbt" if self.include_lags else "calendar_hgbt"

    def fit(self, history: pd.DataFrame, factors: pd.DataFrame | None = None) -> "HourlyGradientBoostingModel":
        ordered = history.sort_values(["route", "timestamp"], ignore_index=True).copy()
        route_totals = ordered.groupby("route")[TARGET_COLUMN].sum()
        self.supported_routes_ = tuple(sorted(route_totals[route_totals > 0].index.astype(int)))
        training = ordered[ordered["route"].isin(self.supported_routes_)].copy()
        features, target = make_training_features(
            training,
            include_lags=self.include_lags,
            include_official_calendar=self.include_official_calendar,
            include_weather=self.include_weather,
            factors=factors,
            weather_columns=self.selected_weather_columns,
        )
        numeric = CALENDAR_NUMERIC_COLUMNS
        if self.include_official_calendar:
            numeric += HOLIDAY_MODEL_COLUMNS
        if self.include_weather:
            numeric += self.selected_weather_columns
        if self.include_lags:
            numeric += LAG_NUMERIC_COLUMNS
        self.pipeline_ = _pipeline(numeric, max_iter=self.max_iter, max_leaf_nodes=self.max_leaf_nodes, random_seed=self.random_seed)
        self.pipeline_.fit(features, target)
        self.history_ = ordered[["route", "date", "hour", "timestamp", TARGET_COLUMN]].copy()
        self.history_start_ = ordered["date"].min()
        self.history_end_ = ordered["date"].max()
        return self

    def _future_features(
        self,
        frame: pd.DataFrame,
        values: dict[tuple[int, pd.Timestamp], float],
        factors: pd.DataFrame | None,
    ) -> pd.DataFrame:
        result = _calendar_features(frame, include_official_calendar=self.include_official_calendar)
        if self.include_weather:
            result = _attach_weather(result, factors, self.selected_weather_columns)
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
        if self.include_official_calendar:
            columns.extend(HOLIDAY_MODEL_COLUMNS)
        if self.include_weather:
            columns.extend(self.selected_weather_columns)
        if self.include_lags:
            columns.extend(LAG_NUMERIC_COLUMNS)
        return result[columns]

    def predict(self, start: date | str, end: date | str, factors: pd.DataFrame | None = None) -> pd.DataFrame:
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
            features = self._future_features(batch, values, factors)
            batch["prediction"] = np.maximum(self.pipeline_.predict(features), 0.0)
            for row in batch.itertuples(index=False):
                values[(int(row.route), row.timestamp)] = float(row.prediction)
            daily_results.append(batch)

        predicted = pd.concat(daily_results, ignore_index=True) if daily_results else grid.iloc[0:0].copy()
        result = grid.merge(predicted[["route", "date", "hour", "prediction"]], on=["route", "date", "hour"], how="left")
        result["status"] = np.where(result["route"].isin(self.supported_routes_), "ok", "cold_start_zero_baseline")
        result["prediction"] = result["prediction"].fillna(0.0).clip(lower=0.0)
        return result


@dataclass
class NativeInteractionGradientBoostingModel(HourlyGradientBoostingModel):
    """Recency-weighted squared-loss model used only as an ensemble component."""

    include_lags: bool = False
    include_official_calendar: bool = True
    include_weather: bool = False
    information_mode: str = "operational"
    max_iter: int = 300
    max_leaf_nodes: int = 31
    half_life_days: float = INTERACTION_HALF_LIFE_DAYS

    @property
    def name(self) -> str:
        return "calendar_interaction_squared_hgbt"

    @property
    def parameter_manifest(self) -> dict[str, object]:
        return {
            "algorithm": "HistGradientBoostingRegressor",
            "loss": "squared_error",
            "learning_rate": 0.05,
            "max_iter": self.max_iter,
            "max_leaf_nodes": self.max_leaf_nodes,
            "min_samples_leaf": 24,
            "l2_regularization": 1.0,
            "recency_half_life_days": self.half_life_days,
            "categorical_features": list(INTERACTION_CATEGORICAL_COLUMNS),
        }

    @property
    def feature_manifest(self) -> dict[str, object]:
        return {
            "categorical": list(INTERACTION_CATEGORICAL_COLUMNS),
            "numeric": list(INTERACTION_NUMERIC_COLUMNS),
            "route_code_order": list(MODELED_ROUTES),
        }

    def fit(
        self,
        history: pd.DataFrame,
        factors: pd.DataFrame | None = None,
    ) -> "NativeInteractionGradientBoostingModel":
        if factors is not None:
            raise ValueError("Interaction model does not use weather factors")
        ordered = history.sort_values(["route", "timestamp"], ignore_index=True).copy()
        route_totals = ordered.groupby("route")[TARGET_COLUMN].sum()
        self.supported_routes_ = tuple(sorted(route_totals[route_totals > 0].index.astype(int)))
        training = ordered[ordered["route"].isin(self.supported_routes_)].copy()
        self.history_end_ = ordered["date"].max()
        age_days = (self.history_end_ - training["date"]).dt.days.to_numpy(dtype=float)
        sample_weight = np.exp(-np.log(2.0) * age_days / self.half_life_days)
        self.pipeline_ = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.05,
            max_iter=self.max_iter,
            max_leaf_nodes=self.max_leaf_nodes,
            min_samples_leaf=24,
            l2_regularization=1.0,
            categorical_features=list(INTERACTION_CATEGORICAL_COLUMNS),
            random_state=RANDOM_SEED,
        )
        self.pipeline_.fit(
            _interaction_features(training),
            training[TARGET_COLUMN].to_numpy(dtype=float),
            sample_weight=sample_weight,
        )
        return self

    def predict(
        self,
        start: date | str,
        end: date | str,
        factors: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        if factors is not None:
            raise ValueError("Interaction model does not use weather factors")
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        if start_ts <= self.history_end_:
            raise ValueError("Prediction start must be after the fitted history")
        grid = full_hourly_grid(start_ts, end_ts, ROUTES)
        supported = grid[grid["route"].isin(self.supported_routes_)].copy()
        supported["prediction"] = np.maximum(
            self.pipeline_.predict(_interaction_features(supported)),
            0.0,
        )
        result = grid.merge(
            supported[["route", "date", "hour", "prediction"]],
            on=["route", "date", "hour"],
            how="left",
            validate="one_to_one",
        )
        result["status"] = np.where(
            result["route"].isin(self.supported_routes_),
            "ok",
            "cold_start_zero_baseline",
        )
        result["prediction"] = result["prediction"].fillna(0.0).clip(lower=0.0)
        return result


@dataclass
class CalendarInteractionEnsembleModel(HourlyGradientBoostingModel):
    """Fixed selection-fold ensemble; weights are never fitted on final validation."""

    include_lags: bool = False
    include_official_calendar: bool = True
    include_weather: bool = False
    information_mode: str = "operational"
    max_iter: int = 300
    max_leaf_nodes: int = 31
    calendar_weight: float = ENSEMBLE_CALENDAR_WEIGHT
    interaction_weight: float = ENSEMBLE_INTERACTION_WEIGHT
    output_scale: float = ENSEMBLE_SCALE

    @property
    def name(self) -> str:
        return "calendar_interaction_ensemble"

    @property
    def parameter_manifest(self) -> dict[str, object]:
        return {
            "combination": "scaled convex blend before submission rounding",
            "calendar_holiday_hgbt_weight": self.calendar_weight,
            "calendar_interaction_squared_hgbt_weight": self.interaction_weight,
            "output_scale": self.output_scale,
            "interaction_component": self.interaction_model_.parameter_manifest
            if hasattr(self, "interaction_model_")
            else NativeInteractionGradientBoostingModel().parameter_manifest,
        }

    @property
    def feature_manifest(self) -> dict[str, object]:
        return {
            "calendar_component": "calendar_holiday_hgbt",
            "interaction_component": NativeInteractionGradientBoostingModel().feature_manifest,
        }

    def fit(
        self,
        history: pd.DataFrame,
        factors: pd.DataFrame | None = None,
    ) -> "CalendarInteractionEnsembleModel":
        if factors is not None:
            raise ValueError("Operational ensemble does not use weather factors")
        self.calendar_model_ = HourlyGradientBoostingModel(
            include_lags=False,
            include_official_calendar=True,
            include_weather=False,
            information_mode="operational",
        ).fit(history)
        self.interaction_model_ = NativeInteractionGradientBoostingModel().fit(history)
        self.supported_routes_ = tuple(
            sorted(set(self.calendar_model_.supported_routes_) & set(self.interaction_model_.supported_routes_))
        )
        self.history_end_ = self.calendar_model_.history_end_
        return self

    def predict(
        self,
        start: date | str,
        end: date | str,
        factors: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        if factors is not None:
            raise ValueError("Operational ensemble does not use weather factors")
        calendar = self.calendar_model_.predict(start, end)
        interaction = self.interaction_model_.predict(start, end)
        keys = ["route", "date", "hour"]
        if not calendar[keys].equals(interaction[keys]):
            raise ValueError("Ensemble components produced different prediction grids")
        result = calendar.copy()
        result["prediction"] = np.maximum(
            self.output_scale
            * (
                self.calendar_weight * calendar["prediction"].to_numpy(dtype=float)
                + self.interaction_weight * interaction["prediction"].to_numpy(dtype=float)
            ),
            0.0,
        )
        return result
