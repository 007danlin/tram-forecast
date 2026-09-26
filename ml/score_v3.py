"""Origin-safe models for the score-v3 passenger-flow study.

The module keeps future target values out of every feature.  Historical
profiles are rebuilt at each training origin, and production inference freezes
the same features at the final observed date.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.data import full_hourly_grid
from ml.factors import HOLIDAY_MODEL_COLUMNS, add_official_calendar_features
from ml.model import (
    CalendarInteractionEnsembleModel,
    HourlyGradientBoostingModel,
    NativeInteractionGradientBoostingModel,
)
from ml.settings import MODELED_ROUTES, ROUTES, TARGET_COLUMN


SCHEMA = "score-v3"
KINDS = ("current_calendar", "current_interaction", "current_ensemble", "direct", "daily", "blend")
BASE_CATEGORICAL = ("route", "dow", "effective_day_type")
DIRECT_CATEGORICAL = (*BASE_CATEGORICAL, "hour", "route_hour", "route_day_type", "hour_day_type")
DAILY_CATEGORICAL = BASE_CATEGORICAL
NUMERIC_COLUMNS = (
    "horizon_day",
    "day_of_year_sin",
    "day_of_year_cos",
    "day_of_year_sin_2",
    "day_of_year_cos_2",
    "darkness_proxy",
    *HOLIDAY_MODEL_COLUMNS,
    "baseline_daily",
    "level_7_mean",
    "level_14_median",
    "level_28_median",
    "level_56_median",
    "type_level_28_median",
    "type_level_56_median",
    "type_observations_56",
    "recent_to_previous_ratio",
    "type_recent_to_previous_ratio",
    "robust_slope_14",
    "zero_share_56",
    "anomaly_count_56",
    "route_share_14",
    "system_level_14",
    "regime_age_days",
    "source_route_change_active",
    "source_coverage_unknown",
)
DIRECT_NUMERIC = (*NUMERIC_COLUMNS, "hourly_share", "hour_profile_observations", "baseline_hour")


def normalize_v3_config(raw: dict) -> dict:
    config = copy.deepcopy(raw)
    allowed = {
        "schema",
        "id",
        "kind",
        "model_name",
        "seed",
        "threads",
        "loss",
        "target_transform",
        "depth",
        "l2_leaf_reg",
        "learning_rate",
        "max_iter",
        "iterations",
        "early_stopping_rounds",
        "inner_days",
        "origin_step",
        "minimum_history",
        "minimum_target_days",
        "horizon",
        "share_window",
        "share_shrinkage",
        "origin_half_life",
        "regime_low_ratio",
        "regime_high_ratio",
        "use_source_regimes",
        "use_detected_regime",
        "component_early_stopping",
        "components",
        "weights",
        "information_mode",
        "weather_columns",
        "weather_groups",
        "alignment",
    }
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("Unexpected score-v3 configuration fields")
    if config.get("schema") != SCHEMA or config.get("kind") not in KINDS:
        raise ValueError("Invalid score-v3 schema or kind")
    kind = config["kind"]
    config.setdefault("id", kind)
    config.setdefault("seed", 20250925)
    config.setdefault("threads", 4)
    config.setdefault("horizon", 61)
    config.setdefault("component_early_stopping", "auto")
    if type(config["seed"]) is not int or type(config["threads"]) is not int or not 1 <= config["threads"] <= 4:
        raise ValueError("Invalid score-v3 seed/thread budget")
    if config["horizon"] != 61:
        raise ValueError("score-v3 is fixed to a direct 61-day horizon")
    if config["component_early_stopping"] not in ("auto", False):
        raise ValueError("Unsupported component early-stopping policy")

    if kind in ("direct", "daily"):
        config.setdefault("loss", "MAE")
        config.setdefault("target_transform", "raw" if kind == "direct" else "residual")
        config.setdefault("depth", 6)
        config.setdefault("l2_leaf_reg", 10.0)
        config.setdefault("learning_rate", 0.05)
        config.setdefault("max_iter", 600)
        config.setdefault("early_stopping_rounds", 75)
        config.setdefault("inner_days", 28)
        config.setdefault("origin_step", 14)
        config.setdefault("minimum_history", 56)
        config.setdefault("minimum_target_days", 14)
        config.setdefault("share_window", 56)
        config.setdefault("share_shrinkage", 4.0)
        config.setdefault("origin_half_life", None)
        config.setdefault("regime_low_ratio", 0.55)
        config.setdefault("regime_high_ratio", 1.45)
        config.setdefault("use_source_regimes", False)
        config.setdefault("use_detected_regime", False)
        if config["loss"] not in ("MAE", "RMSE"):
            raise ValueError("score-v3 supports MAE and RMSE")
        transforms = ("raw",) if kind == "direct" else ("residual", "ratio")
        if config["target_transform"] not in transforms:
            raise ValueError("Invalid score-v3 target transform")
        for field in (
            "depth",
            "max_iter",
            "early_stopping_rounds",
            "inner_days",
            "origin_step",
            "minimum_history",
            "minimum_target_days",
            "share_window",
        ):
            if type(config[field]) is not int or config[field] <= 0:
                raise ValueError(f"Invalid positive integer: {field}")
        if "iterations" in config and (type(config["iterations"]) is not int or config["iterations"] <= 0):
            raise ValueError("iterations must be a positive integer")
        if not 0 < config["regime_low_ratio"] < 1 < config["regime_high_ratio"]:
            raise ValueError("Invalid fixed regime thresholds")
    elif kind == "blend":
        components = [normalize_v3_config(component) for component in config.get("components", [])]
        weights = np.asarray(config.get("weights", []), dtype=float)
        if len(components) < 2 or len(weights) != len(components):
            raise ValueError("score-v3 blend needs matching components and weights")
        if not np.isfinite(weights).all() or (weights <= 0).any() or not np.isclose(weights.sum(), 1.0):
            raise ValueError("score-v3 blend weights must be positive and sum to one")
        config["components"] = components
        config["weights"] = weights.tolist()

    derived = {
        "model_name": f"score_v3_{kind}",
        "information_mode": "operational",
        "weather_columns": [],
        "weather_groups": [],
        "alignment": "origin_history_v1",
    }
    for field, value in derived.items():
        if field in config and config[field] != value:
            raise ValueError(f"Inconsistent score-v3 {field}")
        config[field] = value
    return config


def score_v3_config(kind: str, id: str, **kwargs) -> dict:
    return normalize_v3_config({"schema": SCHEMA, "kind": kind, "id": id, **kwargs})


def _calendar(frame: pd.DataFrame) -> pd.DataFrame:
    result = add_official_calendar_features(frame.copy())
    result["dow"] = result["date"].dt.dayofweek.astype("int8")
    special = result["is_public_holiday"].eq(1) | result["is_transferred_day_off"].eq(1)
    result["effective_day_type"] = np.select(
        [special, result["is_day_off"].eq(1)],
        ["holiday", "day_off"],
        default="workday",
    )
    day = result["date"].dt.dayofyear.to_numpy(dtype=float)
    angle = 2.0 * np.pi * day / 365.25
    result["day_of_year_sin"] = np.sin(angle)
    result["day_of_year_cos"] = np.cos(angle)
    result["day_of_year_sin_2"] = np.sin(2.0 * angle)
    result["day_of_year_cos_2"] = np.cos(2.0 * angle)
    # Deterministic seasonal darkness proxy for Moscow; no future observation.
    result["darkness_proxy"] = (1.0 + np.cos(2.0 * np.pi * (day - 355.0) / 365.25)) / 2.0
    return result


def _effective_type(frame: pd.DataFrame) -> pd.Series:
    return _calendar(frame[["date"]].copy())["effective_day_type"]


def _source_features(origin: pd.Timestamp, targets: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    active = np.zeros(len(targets), dtype=float)
    unknown = np.zeros(len(targets), dtype=float)
    route = targets["route"].to_numpy()
    date = targets["date"].to_numpy(dtype="datetime64[ns]")
    # T01 was published before 10 July with a planned duration up to 28 days.
    # The exact 13 August restoration became available only on 13 August.
    if origin >= pd.Timestamp("2025-07-09"):
        known_end = pd.Timestamp("2025-08-13") if origin >= pd.Timestamp("2025-08-13") else pd.Timestamp("2025-08-06")
        mask = np.isin(route, [7, 50]) & (date >= np.datetime64("2025-07-10")) & (date <= known_end.to_datetime64())
        active[mask] = 1.0
        if origin < pd.Timestamp("2025-08-13"):
            unknown[mask] = 1.0
    return active, unknown


@dataclass
class OriginSnapshot:
    history: pd.DataFrame
    config: dict

    def __post_init__(self) -> None:
        self.origin = self.history["date"].max()
        daily = self.history.groupby(["route", "date"], as_index=False)[TARGET_COLUMN].sum()
        daily["effective_day_type"] = _effective_type(daily)
        daily["dow"] = daily["date"].dt.dayofweek.astype("int8")
        self.daily = daily.sort_values(["route", "date"], ignore_index=True)
        self._states = self._build_states()

    def _build_states(self) -> dict[tuple[int, str, int], dict[str, float]]:
        states: dict[tuple[int, str, int], dict[str, float]] = {}
        all_daily = self.daily
        total_recent = (
            all_daily[all_daily.date > self.origin - pd.Timedelta(days=14)]
            .groupby("date")[TARGET_COLUMN]
            .sum()
            .mean()
        )
        for route in MODELED_ROUTES:
            route_daily = all_daily[all_daily.route.eq(route)].copy()
            by_window: dict[int, pd.Series] = {
                days: route_daily.loc[route_daily.date > self.origin - pd.Timedelta(days=days), TARGET_COLUMN]
                for days in (7, 14, 28, 56)
            }
            previous = route_daily[
                route_daily.date.between(
                    self.origin - pd.Timedelta(days=41),
                    self.origin - pd.Timedelta(days=14),
                )
            ][TARGET_COLUMN]
            recent_14_mean = float(by_window[14].mean()) if len(by_window[14]) else 0.0
            previous_median = float(previous.median()) if len(previous) else np.nan
            recent_median = float(by_window[14].median()) if len(by_window[14]) else np.nan
            ratio = recent_median / previous_median if previous_median and np.isfinite(previous_median) else 1.0
            recent7 = route_daily[route_daily.date > self.origin - pd.Timedelta(days=7)][TARGET_COLUMN]
            prior7 = route_daily[
                route_daily.date.between(
                    self.origin - pd.Timedelta(days=13),
                    self.origin - pd.Timedelta(days=7),
                )
            ][TARGET_COLUMN]
            slope = (recent7.median() - prior7.median()) / max(float(prior7.median()), 1.0) if len(prior7) else 0.0
            last56 = by_window[56]
            median56 = float(last56.median()) if len(last56) else 0.0
            mad56 = float(np.median(np.abs(last56.to_numpy(dtype=float) - median56))) if len(last56) else 0.0
            anomaly_count = int((np.abs(last56 - median56) > max(3.0 * mad56, 1.0)).sum())
            system_without_route = max(float(total_recent or 0.0) - recent_14_mean, 0.0)

            for day_type in ("workday", "day_off", "holiday"):
                for dow in range(7):
                    comparable_type = day_type
                    comparable = route_daily[
                        route_daily.effective_day_type.eq(comparable_type) & route_daily.dow.eq(dow)
                    ]
                    if day_type == "holiday" and len(comparable) < 3:
                        comparable_type = "day_off"
                        comparable = route_daily[route_daily.effective_day_type.eq(comparable_type)]
                    elif len(comparable) < 3:
                        comparable = route_daily[route_daily.effective_day_type.eq(comparable_type)]
                    typed56 = comparable[comparable.date.gt(self.origin - pd.Timedelta(days=56))]
                    typed28 = typed56[typed56.date > self.origin - pd.Timedelta(days=28)]
                    typed_recent = typed56[typed56.date > self.origin - pd.Timedelta(days=14)][TARGET_COLUMN]
                    typed_previous = typed56[
                        typed56.date.between(
                            self.origin - pd.Timedelta(days=41),
                            self.origin - pd.Timedelta(days=14),
                        )
                    ][TARGET_COLUMN]
                    type_ratio = (
                        float(typed_recent.median()) / float(typed_previous.median())
                        if len(typed_recent) and len(typed_previous) and float(typed_previous.median()) > 0
                        else 1.0
                    )
                    changes = []
                    series = comparable.sort_values("date")
                    values = series[TARGET_COLUMN].to_numpy(dtype=float)
                    dates = series.date.to_numpy()
                    for index in range(4, len(series)):
                        reference = float(np.median(values[max(0, index - 4):index]))
                        current_ratio = values[index] / reference if reference > 0 else 1.0
                        if current_ratio < self.config["regime_low_ratio"] or current_ratio > self.config["regime_high_ratio"]:
                            changes.append(pd.Timestamp(dates[index]))
                    regime_age = float((self.origin - changes[-1]).days) if changes else 999.0
                    baseline = float(typed56[TARGET_COLUMN].median()) if len(typed56) >= 3 else float(by_window[28].median())
                    states[(route, day_type, dow)] = {
                    "baseline_daily": max(baseline, 0.0),
                    "level_7_mean": float(by_window[7].mean()),
                    "level_14_median": float(by_window[14].median()),
                    "level_28_median": float(by_window[28].median()),
                    "level_56_median": median56,
                    "type_level_28_median": float(typed28[TARGET_COLUMN].median()) if len(typed28) else baseline,
                    "type_level_56_median": float(typed56[TARGET_COLUMN].median()) if len(typed56) else baseline,
                    "type_observations_56": float(len(typed56)),
                    "recent_to_previous_ratio": float(np.clip(ratio, 0.0, 4.0)),
                    "type_recent_to_previous_ratio": float(np.clip(type_ratio, 0.0, 4.0)),
                    "robust_slope_14": float(np.clip(slope, -2.0, 2.0)),
                    "zero_share_56": float(last56.eq(0).mean()) if len(last56) else 0.0,
                    "anomaly_count_56": float(anomaly_count),
                    "route_share_14": recent_14_mean / max(float(total_recent or 0.0), 1.0),
                    "system_level_14": system_without_route,
                    "regime_age_days": min(regime_age, 999.0),
                    }
        return states

    def calendar_features(self, targets: pd.DataFrame, *, include_hour: bool) -> pd.DataFrame:
        data = _calendar(targets.copy())
        data["horizon_day"] = (data["date"] - self.origin).dt.days.astype("int16")
        state_rows = [
            self._states[(int(route), day_type, int(dow))]
            for route, day_type, dow in zip(data.route, data.effective_day_type, data.dow)
        ]
        state = pd.DataFrame(state_rows, index=data.index)
        for column in state:
            data[column] = state[column]
        if not self.config.get("use_detected_regime", False):
            data["regime_age_days"] = 999.0
        if self.config["use_source_regimes"]:
            active, unknown = _source_features(self.origin, data)
            data["source_route_change_active"] = active
            data["source_coverage_unknown"] = unknown
        else:
            data["source_route_change_active"] = 0.0
            data["source_coverage_unknown"] = 0.0
        data["route"] = data["route"].astype(str)
        data["dow"] = data["dow"].astype(str)
        if include_hour:
            data["hour"] = data["hour"].astype(str)
            data["route_hour"] = data["route"] + "_" + data["hour"]
            data["route_day_type"] = data["route"] + "_" + data["effective_day_type"]
            data["hour_day_type"] = data["hour"] + "_" + data["effective_day_type"]
        return data

    def hourly_shares(self, targets: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        start = self.origin - pd.Timedelta(days=self.config["share_window"] - 1)
        history = self.history[self.history.date.ge(start)].copy()
        history["effective_day_type"] = _effective_type(history)
        history["dow"] = history["date"].dt.dayofweek.astype("int8")
        daily_total = history.groupby(["route", "date"])[TARGET_COLUMN].transform("sum")
        history["share"] = np.divide(
            history[TARGET_COLUMN].to_numpy(dtype=float),
            daily_total.to_numpy(dtype=float),
            out=np.zeros(len(history), dtype=float),
            where=daily_total.to_numpy(dtype=float) > 0,
        )
        typed = history.groupby(["route", "effective_day_type", "dow", "hour"]).share.agg(["median", "count"])
        typed_general = history.groupby(["route", "effective_day_type", "hour"]).share.agg(["median", "count"])
        route_hour = history.groupby(["route", "hour"]).share.median()
        global_hour = history.groupby("hour").share.median()
        values = []
        observations = []
        target_types = _effective_type(targets)
        target_dows = targets["date"].dt.dayofweek
        shrinkage = float(self.config["share_shrinkage"])
        for route, day_type, dow, hour in zip(targets.route, target_types, target_dows, targets.hour):
            key = (int(route), day_type, int(dow), int(hour))
            if key not in typed.index and day_type == "holiday":
                general_key = (int(route), "day_off", int(hour))
            else:
                general_key = (int(route), day_type, int(hour))
            general = float(route_hour.get((int(route), int(hour)), global_hour.get(int(hour), 1.0 / 24.0)))
            if key in typed.index:
                row = typed.loc[key]
                count = float(row["count"])
                weight = count / (count + shrinkage)
                value = weight * float(row["median"]) + (1.0 - weight) * general
            elif general_key in typed_general.index:
                row = typed_general.loc[general_key]
                count = float(row["count"])
                weight = count / (count + shrinkage)
                value = weight * float(row["median"]) + (1.0 - weight) * general
            else:
                count = 0.0
                value = general
            values.append(max(value, 0.0))
            observations.append(count)
        result = np.asarray(values, dtype=float)
        groups = targets[["route", "date"]].copy()
        groups["share"] = result
        totals = groups.groupby(["route", "date"]).share.transform("sum").to_numpy(dtype=float)
        result = np.divide(result, totals, out=np.full(len(result), 1.0 / 24.0), where=totals > 0)
        return result, np.asarray(observations, dtype=float)


class ScoreV3Model:
    include_lags = False
    include_official_calendar = True
    include_weather = False
    information_mode = "operational"
    selected_weather_columns: tuple[str, ...] = ()

    def __init__(self, experiment_config: dict):
        self.experiment_config = normalize_v3_config(experiment_config)
        self.name = self.experiment_config["model_name"]
        self.max_iter = self.experiment_config.get("max_iter", 300)
        self.max_leaf_nodes = 31

    def _origins(self, history: pd.DataFrame) -> list[pd.Timestamp]:
        config = self.experiment_config
        first = history.date.min() + pd.Timedelta(days=config["minimum_history"] - 1)
        last = history.date.max() - pd.Timedelta(days=config["minimum_target_days"])
        if last < first:
            raise ValueError("Insufficient history for score-v3 origins")
        return list(pd.date_range(first, last, freq=f"{config['origin_step']}D"))

    def _training_examples(self, history: pd.DataFrame) -> pd.DataFrame:
        config = self.experiment_config
        kind = config["kind"]
        parts = []
        daily_actual = history.groupby(["route", "date"], as_index=False)[TARGET_COLUMN].sum()
        for origin in self._origins(history):
            past = history[history.date.le(origin)].copy()
            end = min(origin + pd.Timedelta(days=config["horizon"]), history.date.max())
            snapshot = OriginSnapshot(past, config)
            if kind == "daily":
                actual = daily_actual[daily_actual.date.between(origin + pd.Timedelta(days=1), end)].copy()
                features = snapshot.calendar_features(actual[["route", "date"]], include_hour=False)
                target = actual[TARGET_COLUMN].to_numpy(dtype=float)
            else:
                actual = history[history.date.between(origin + pd.Timedelta(days=1), end)].copy()
                features = snapshot.calendar_features(actual[["route", "date", "hour"]], include_hour=True)
                shares, counts = snapshot.hourly_shares(actual[["route", "date", "hour"]])
                features["hourly_share"] = shares
                features["hour_profile_observations"] = counts
                features["baseline_hour"] = features["baseline_daily"].to_numpy(dtype=float) * shares
                target = actual[TARGET_COLUMN].to_numpy(dtype=float)
            features["_origin"] = origin
            features["_target_date"] = actual["date"].to_numpy()
            features["_y"] = target
            parts.append(features)
        if not parts:
            raise ValueError("No score-v3 training examples")
        data = pd.concat(parts, ignore_index=True)
        if config["kind"] == "daily":
            baseline = data["baseline_daily"].to_numpy(dtype=float)
            if config["target_transform"] == "residual":
                data["_fit_y"] = data["_y"] - baseline
            else:
                data["_fit_y"] = np.divide(
                    data["_y"],
                    baseline,
                    out=np.ones(len(data), dtype=float),
                    where=baseline > 0,
                ).clip(0.0, 4.0)
        else:
            data["_fit_y"] = data["_y"]
        keys = ["route", "_target_date"] + (["hour"] if config["kind"] == "direct" else [])
        data["_duplicate_count"] = data.groupby(keys)["_target_date"].transform("size").astype(float)
        return data

    def _estimator(self, iterations: int):
        from catboost import CatBoostRegressor

        config = self.experiment_config
        return CatBoostRegressor(
            loss_function=config["loss"],
            eval_metric=config["loss"],
            learning_rate=config["learning_rate"],
            depth=config["depth"],
            l2_leaf_reg=config["l2_leaf_reg"],
            iterations=iterations,
            random_seed=config["seed"],
            thread_count=config["threads"],
            task_type="CPU",
            allow_writing_files=False,
            verbose=False,
        )

    def _weights(self, data: pd.DataFrame) -> np.ndarray:
        config = self.experiment_config
        weight = 1.0 / data["_duplicate_count"].to_numpy(dtype=float)
        if config["kind"] == "daily" and config["target_transform"] == "ratio":
            weight *= np.maximum(data["baseline_daily"].to_numpy(dtype=float), 1.0)
        if config["origin_half_life"] is not None:
            age = (self.history_end_ - data["_origin"]).dt.days.to_numpy(dtype=float)
            weight *= 2.0 ** (-age / float(config["origin_half_life"]))
        return weight

    def fit(self, history: pd.DataFrame, factors=None) -> "ScoreV3Model":
        if factors is not None:
            raise ValueError("score-v3 operational models do not use future weather")
        if history.empty or history.date.max() > pd.Timestamp("2025-10-31"):
            raise ValueError("Empty or forbidden score-v3 target history")
        config = self.experiment_config
        ordered = history[history.route.isin(MODELED_ROUTES)].sort_values(["route", "date", "hour"], ignore_index=True).copy()
        totals = ordered.groupby("route")[TARGET_COLUMN].sum()
        self.supported_routes_ = tuple(int(route) for route in totals[totals > 0].index)
        ordered = ordered[ordered.route.isin(self.supported_routes_)].copy()
        self.history_ = ordered
        self.history_start_ = ordered.date.min()
        self.history_end_ = ordered.date.max()
        kind = config["kind"]
        if kind in ("current_calendar", "current_interaction", "current_ensemble"):
            if kind == "current_calendar":
                self.delegate_ = HourlyGradientBoostingModel(
                    include_lags=False,
                    include_official_calendar=True,
                    include_weather=False,
                    information_mode="operational",
                    early_stopping=config["component_early_stopping"],
                ).fit(ordered)
            elif kind == "current_interaction":
                self.delegate_ = NativeInteractionGradientBoostingModel(
                    early_stopping=config["component_early_stopping"]
                ).fit(ordered)
            else:
                self.delegate_ = CalendarInteractionEnsembleModel(
                    component_early_stopping=config["component_early_stopping"]
                ).fit(ordered)
            self.fit_details_ = {
                "train_start": str(self.history_start_.date()),
                "train_end": str(self.history_end_.date()),
                "component_early_stopping": config["component_early_stopping"],
            }
            return self
        if kind == "blend":
            self.components_ = [ScoreV3Model(component).fit(ordered) for component in config["components"]]
            self.fit_details_ = {
                "train_start": str(self.history_start_.date()),
                "train_end": str(self.history_end_.date()),
                "components": [component.fit_details_ for component in self.components_],
            }
            return self

        data = self._training_examples(ordered)
        categorical = DIRECT_CATEGORICAL if kind == "direct" else DAILY_CATEGORICAL
        numeric = DIRECT_NUMERIC if kind == "direct" else NUMERIC_COLUMNS
        self.feature_columns_ = [*categorical, *numeric]
        features = data[self.feature_columns_].copy()
        for column in categorical:
            features[column] = features[column].astype(str)
        target = data["_fit_y"].to_numpy(dtype=float)
        weights = self._weights(data)
        split = self.history_end_ - pd.Timedelta(days=config["inner_days"])
        inner = data["_target_date"].le(split).to_numpy()
        validation = data["_target_date"].gt(split).to_numpy()
        iterations = config.get("iterations")
        from catboost import Pool

        with threadpool_limits(limits=config["threads"]):
            if iterations is None:
                if not inner.any() or not validation.any():
                    raise ValueError("No temporal inner train/validation rows")
                probe = self._estimator(config["max_iter"])
                probe.fit(
                    Pool(features.loc[inner], target[inner], cat_features=list(categorical), weight=weights[inner]),
                    eval_set=Pool(
                        features.loc[validation],
                        target[validation],
                        cat_features=list(categorical),
                        weight=weights[validation],
                    ),
                    early_stopping_rounds=config["early_stopping_rounds"],
                    use_best_model=True,
                )
                iterations = max(1, int(probe.get_best_iteration()) + 1)
            self.estimator_ = self._estimator(iterations)
            self.estimator_.fit(
                Pool(features, target, cat_features=list(categorical), weight=weights)
            )
        self.fit_details_ = {
            "train_start": str(self.history_start_.date()),
            "train_end": str(self.history_end_.date()),
            "origins": len(self._origins(ordered)),
            "training_rows": len(data),
            "iterations": int(iterations),
            "inner_cutoff": str(split.date()),
            "loss": config["loss"],
            "target_transform": config["target_transform"],
            "duplicate_weighting": "inverse repetitions of the same outer target key",
        }
        return self

    def predict(self, start, end, factors=None) -> pd.DataFrame:
        if factors is not None:
            raise ValueError("score-v3 operational models do not use future weather")
        start_ts, end_ts = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        if start_ts <= self.history_end_ or (end_ts - self.history_end_).days > 61:
            raise ValueError("score-v3 prediction must be the next 1..61 days")
        config = self.experiment_config
        grid = full_hourly_grid(start_ts, end_ts, ROUTES)
        supported = grid[grid.route.isin(self.supported_routes_)].copy()
        kind = config["kind"]
        if kind in ("current_calendar", "current_interaction", "current_ensemble"):
            return self.delegate_.predict(start_ts, end_ts)
        if kind == "blend":
            outputs = [component.predict(start_ts, end_ts) for component in self.components_]
            keys = ["route", "date", "hour"]
            if any(not outputs[0][keys].equals(output[keys]) for output in outputs[1:]):
                raise ValueError("score-v3 blend component grid mismatch")
            result = outputs[0].copy()
            result["prediction"] = sum(
                weight * output.prediction.to_numpy(dtype=float)
                for weight, output in zip(config["weights"], outputs)
            )
            result["prediction"] = np.maximum(result["prediction"], 0.0)
            return result

        snapshot = OriginSnapshot(self.history_, config)
        if kind == "direct":
            features = snapshot.calendar_features(supported[["route", "date", "hour"]], include_hour=True)
            shares, counts = snapshot.hourly_shares(supported[["route", "date", "hour"]])
            features["hourly_share"] = shares
            features["hour_profile_observations"] = counts
            features["baseline_hour"] = features["baseline_daily"].to_numpy(dtype=float) * shares
            prediction = self.estimator_.predict(features[self.feature_columns_])
        else:
            days = supported[["route", "date"]].drop_duplicates(ignore_index=True)
            features = snapshot.calendar_features(days, include_hour=False)
            correction = self.estimator_.predict(features[self.feature_columns_])
            baseline = features["baseline_daily"].to_numpy(dtype=float)
            if config["target_transform"] == "residual":
                daily_prediction = baseline + correction
            else:
                daily_prediction = baseline * np.clip(correction, 0.0, 4.0)
            days["daily_prediction"] = np.maximum(daily_prediction, 0.0)
            shares, _ = snapshot.hourly_shares(supported[["route", "date", "hour"]])
            supported["_share"] = shares
            supported = supported.merge(days, on=["route", "date"], validate="many_to_one")
            prediction = supported["daily_prediction"].to_numpy(dtype=float) * supported["_share"].to_numpy(dtype=float)
        supported["prediction"] = np.maximum(prediction, 0.0)
        result = grid.merge(
            supported[["route", "date", "hour", "prediction"]],
            on=["route", "date", "hour"],
            how="left",
            validate="one_to_one",
        )
        result["status"] = np.where(
            result.route.isin(self.supported_routes_),
            "ok",
            "cold_start_zero_baseline",
        )
        result["prediction"] = result["prediction"].fillna(0.0).clip(lower=0.0)
        return result
