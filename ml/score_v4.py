"""Origin-safe candidates for the bounded score-v4 study.

The incumbent model is never mutated.  Calibrators train on rolling-origin
incumbent forecasts, and the two B ablations are isolated reimplementations of
the incumbent components with one declared feature change each.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from ml.data import full_hourly_grid
from ml.factors import HOLIDAY_MODEL_COLUMNS, add_official_calendar_features
from ml.model import (
    CalendarInteractionEnsembleModel,
    ENSEMBLE_CALENDAR_WEIGHT,
    ENSEMBLE_INTERACTION_WEIGHT,
    ENSEMBLE_SCALE,
    HGBT_FIXED_PARAMETERS,
    INTERACTION_HALF_LIFE_DAYS,
)
from ml.settings import KEY_COLUMNS, MODELED_ROUTES, RANDOM_SEED, ROUTES, TARGET_COLUMN
from ml.score_v3 import ScoreV3Model


V4_SCHEMA = "score-v4"
BASE_INTERACTION_CATEGORICAL = (
    "route_code", "hour", "dow", "month", "route_hour", "route_dow", "hour_dow", "week"
)
INTERACTION_NUMERIC = (*HOLIDAY_MODEL_COLUMNS, "day_of_year_sin", "day_of_year_cos")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def official_day_type(frame: pd.DataFrame) -> pd.Series:
    calendar = add_official_calendar_features(frame[["date"]].copy())
    holiday = calendar["is_public_holiday"].eq(1) | calendar["is_transferred_day_off"].eq(1)
    return pd.Series(
        np.select([holiday, calendar["is_day_off"].eq(1)], ["holiday", "day_off"], default="workday"),
        index=frame.index,
        dtype="object",
    )


def route_origin_state(history: pd.DataFrame, *, down: float = 0.9, up: float = 1.1) -> pd.DataFrame:
    """Past-only route state at the final history date."""
    origin = pd.Timestamp(history["date"].max())
    daily = history.groupby(["route", "date"], as_index=False)[TARGET_COLUMN].sum()
    rows = []
    for route in MODELED_ROUTES:
        values = daily[daily.route.eq(route)]
        recent = values[values.date.gt(origin - pd.Timedelta(days=14))][TARGET_COLUMN]
        previous = values[
            values.date.between(origin - pd.Timedelta(days=42), origin - pd.Timedelta(days=15))
        ][TARGET_COLUMN]
        recent_level = float(recent.median()) if len(recent) else 0.0
        previous_level = float(previous.median()) if len(previous) else 0.0
        ratio = recent_level / previous_level if previous_level > 0 else 1.0
        bucket = "down" if ratio < down else ("up" if ratio > up else "stable")
        rows.append({"route": route, "origin_level_ratio": float(np.clip(ratio, 0.0, 4.0)), "state": bucket})
    return pd.DataFrame(rows)


def attach_origin_features(rows: pd.DataFrame, history: pd.DataFrame, *, down: float, up: float) -> pd.DataFrame:
    result = rows.copy()
    result["date"] = pd.to_datetime(result["date"])
    origins = result["date"] - pd.to_timedelta(result["horizon_day"], unit="D")
    if origins.nunique() != 1:
        raise ValueError("Origin features require one fixed forecast origin")
    history = history[history.date.le(origins.iloc[0])].copy()
    if history.empty:
        raise ValueError("No history available before forecast origin")
    result["day_type"] = official_day_type(result)
    result["dow"] = result["date"].dt.dayofweek.astype("int8")
    result["horizon_band"] = pd.cut(
        result["horizon_day"], [0, 7, 30, 61], labels=["1-7", "8-30", "31-61"]
    ).astype(str)
    result = result.merge(route_origin_state(history, down=down, up=up), on="route", validate="many_to_one")
    return result


def internal_origins(history: pd.DataFrame, config: dict) -> list[pd.Timestamp]:
    start = pd.Timestamp(history.date.min()) + pd.Timedelta(days=config["minimum_history_days"] - 1)
    stop = pd.Timestamp(history.date.max()) - pd.Timedelta(days=config["minimum_target_days"])
    if stop < start:
        raise ValueError("Insufficient history for score-v4 internal OOF")
    return list(pd.date_range(start, stop, freq=f"{config['origin_step_days']}D"))


def origin_grid_audit(origins: list[pd.Timestamp], horizon: int, history_end: pd.Timestamp) -> dict:
    rows = []
    for origin in origins:
        available = min(horizon, (history_end - origin).days)
        rows.extend((origin.dayofweek, h) for h in range(1, available + 1))
    frame = pd.DataFrame(rows, columns=["origin_dow", "horizon_day"])
    table = frame.groupby(["origin_dow", "horizon_day"]).size().unstack(fill_value=0)
    return {
        "origins": len(origins),
        "origin_dates": [str(value.date()) for value in origins],
        "origin_dow_counts": {
            str(int(k)): int(v)
            for k, v in pd.Series([origin.dayofweek for origin in origins]).value_counts().sort_index().items()
        },
        "represented_origin_dow": sorted(int(value) for value in frame.origin_dow.unique()),
        "horizon_effective_counts": {str(int(k)): int(v) for k, v in frame.groupby("horizon_day").size().items()},
        "dow_horizon_counts": {
            str(dow): {str(h): int(table.get(h, pd.Series(dtype=int)).get(dow, 0)) for h in range(1, horizon + 1)}
            for dow in range(7)
        },
        "dow_horizon_nonzero_cells": int((table > 0).sum().sum()),
        "dow_horizon_total_cells": int(7 * horizon),
    }


def _component_forecasts(model: CalendarInteractionEnsembleModel, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    calendar = model.calendar_model_.predict(start, end)[[*KEY_COLUMNS, "prediction"]].rename(columns={"prediction": "b0"})
    interaction = model.interaction_model_.predict(start, end)[[*KEY_COLUMNS, "prediction"]].rename(columns={"prediction": "b1"})
    result = calendar.merge(interaction, on=list(KEY_COLUMNS), validate="one_to_one")
    result["b2"] = ENSEMBLE_SCALE * (
        ENSEMBLE_CALENDAR_WEIGHT * result["b0"] + ENSEMBLE_INTERACTION_WEIGHT * result["b1"]
    )
    result["b2"] = result["b2"].clip(lower=0.0)
    return result


def build_internal_b2_oof(history: pd.DataFrame, config: dict, cache_dir: str | Path) -> tuple[pd.DataFrame, dict]:
    """Build or validate a cache of honest B2 component forecasts."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    origins = internal_origins(history, config)
    parts, records = [], []
    for origin in origins:
        destination = cache / f"origin-{origin.date()}.csv"
        record_path = destination.with_suffix(".json")
        end = min(origin + pd.Timedelta(days=config["horizon_days"]), pd.Timestamp(history.date.max()))
        identity = {
            "schema": V4_SCHEMA,
            "origin": str(origin.date()),
            "end": str(end.date()),
            "history_start": str(pd.Timestamp(history.date.min()).date()),
            "history_end": str(pd.Timestamp(history.date.max()).date()),
            "rows_before_origin": int(history.date.le(origin).sum()),
        }
        if destination.exists() and record_path.exists():
            saved = json.loads(record_path.read_text(encoding="utf-8"))
            if saved["identity"] != identity or saved["sha256"] != sha256_file(destination):
                raise ValueError(f"Invalid internal B2 cache: {destination}")
            part = pd.read_csv(destination, parse_dates=["date", "origin"], float_precision="round_trip")
            records.append(saved)
            parts.append(part)
            continue
        past = history[history.date.le(origin)].copy()
        actual = history[history.date.between(origin + pd.Timedelta(days=1), end)].copy()
        started = time.monotonic()
        model = CalendarInteractionEnsembleModel().fit(past)
        forecast = _component_forecasts(model, origin + pd.Timedelta(days=1), end)
        part = actual[[*KEY_COLUMNS, TARGET_COLUMN]].merge(forecast, on=list(KEY_COLUMNS), validate="one_to_one")
        part = part[part.route.isin(MODELED_ROUTES)].copy()
        part["origin"] = origin
        part["horizon_day"] = (part["date"] - origin).dt.days.astype("int16")
        state = route_origin_state(past)
        part = part.merge(state, on="route", validate="many_to_one")
        part["day_type"] = official_day_type(part)
        part["dow"] = part["date"].dt.dayofweek.astype("int8")
        part["horizon_band"] = pd.cut(part["horizon_day"], [0, 7, 30, 61], labels=["1-7", "8-30", "31-61"]).astype(str)
        keys = ["route", "date", "hour"]
        part.to_csv(destination, index=False, encoding="utf-8", lineterminator="\n")
        saved = {
            "identity": identity,
            "sha256": sha256_file(destination),
            "seconds": time.monotonic() - started,
            "rows": len(part),
            "keys": keys,
        }
        record_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        joblib.dump(model, cache / f"origin-{origin.date()}.joblib", compress=3)
        records.append(saved)
        parts.append(part)
    result = pd.concat(parts, ignore_index=True)
    duplicate_keys = ["route", "date", "hour"]
    result["duplicate_count"] = result.groupby(duplicate_keys)["date"].transform("size").astype(float)
    audit = origin_grid_audit(origins, config["horizon_days"], pd.Timestamp(history.date.max()))
    audit.update({"rows": len(result), "unique_target_keys": int(result[duplicate_keys].drop_duplicates().shape[0]), "fits": records})
    return result, audit


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not valid.any():
        return 1.0
    values, weights = values[valid], weights[valid]
    order = np.argsort(values, kind="stable")
    values, weights = values[order], weights[order]
    return float(values[np.searchsorted(np.cumsum(weights), weights.sum() / 2.0, side="left")])


@dataclass
class HierarchicalLevelCalibrator:
    lower: float
    upper: float
    shrinkage: float

    def fit(self, data: pd.DataFrame) -> "HierarchicalLevelCalibrator":
        frame = data[data.b2.gt(0)].copy()
        ratio = frame[TARGET_COLUMN].to_numpy(dtype=float) / frame.b2.to_numpy(dtype=float)
        weight = frame.b2.to_numpy(dtype=float) / frame.duplicate_count.to_numpy(dtype=float)
        self.global_ = float(np.clip(weighted_median(
            np.append(ratio, 1.0), np.append(weight, self.shrinkage)
        ), self.lower, self.upper))
        frame["ratio"] = ratio
        frame["weight"] = weight
        self.route_ = self._groups(frame, ["route"], {(): self.global_}, self.shrinkage)
        self.day_type_ = self._groups(frame, ["route", "day_type"], self.route_, self.shrinkage * 2.0)
        self.state_ = self._groups(frame, ["route", "day_type", "state"], self.day_type_, self.shrinkage * 4.0)
        return self

    def _groups(self, frame: pd.DataFrame, columns: list[str], parents: dict, shrinkage: float) -> dict:
        result = {}
        for key, group in frame.groupby(columns, sort=True, observed=True):
            key = key if isinstance(key, tuple) else (key,)
            parent_key = key[:-1]
            parent = parents.get(parent_key, parents.get(key[:1], self.global_))
            values = np.append(group.ratio.to_numpy(dtype=float), parent)
            weights = np.append(group.weight.to_numpy(dtype=float), shrinkage)
            result[key] = float(np.clip(weighted_median(values, weights), self.lower, self.upper))
        return result

    def predict_factor(self, rows: pd.DataFrame) -> np.ndarray:
        factors = []
        for row in rows.itertuples(index=False):
            state_key = (int(row.route), row.day_type, row.state)
            day_key = (int(row.route), row.day_type)
            route_key = (int(row.route),)
            factors.append(self.state_.get(state_key, self.day_type_.get(day_key, self.route_.get(route_key, self.global_))))
        return np.asarray(factors, dtype=float)


def fixed_origin_tuning_split(data: pd.DataFrame, fraction: float) -> tuple[np.ndarray, np.ndarray, dict]:
    """Tune at one origin, purging targets unavailable at that origin."""
    origins = sorted(pd.to_datetime(data.origin.unique()))
    if len(origins) < 2:
        raise ValueError("Insufficient origins for honest inner tuning")
    split_index = min(len(origins) - 1, max(1, int(np.floor(len(origins) * (1.0 - fraction)))))
    cutoff = origins[split_index]
    train = (data.origin.lt(cutoff) & data.date.le(cutoff)).to_numpy()
    validation = (data.origin.eq(cutoff) & data.date.gt(cutoff)).to_numpy()
    if not train.any() or not validation.any():
        raise ValueError("Insufficient past-only inner train/validation rows")
    audit = {
        "rule": "one fixed validation origin; training target dates <= that origin",
        "origin": str(cutoff.date()), "train_rows": int(train.sum()),
        "train_max_target_date": str(data.loc[train, "date"].max().date()),
        "validation_rows": int(validation.sum()),
        "validation_days": int(data.loc[validation, "date"].nunique()),
        "validation_end": str(data.loc[validation, "date"].max().date()),
        "partial_window": int(data.loc[validation, "date"].nunique()) < 61,
    }
    return train, validation, audit


def fit_a1(internal: pd.DataFrame, config: dict) -> tuple[HierarchicalLevelCalibrator, dict]:
    train_mask, validation_mask, audit = fixed_origin_tuning_split(internal, config["tuning_fraction"])
    fit_rows = internal.loc[train_mask].copy()
    fit_rows["duplicate_count"] = fit_rows.groupby(["route", "date", "hour"])["date"].transform("size").astype(float)
    validation = internal.loc[validation_mask]
    trials = []
    for lower, upper in config["bounds"]:
        for shrinkage in config["shrinkage"]:
            model = HierarchicalLevelCalibrator(lower, upper, shrinkage).fit(fit_rows)
            prediction = validation.b2.to_numpy(dtype=float) * model.predict_factor(validation)
            rounded = np.floor(np.maximum(prediction, 0.0) + 0.5)
            sae = float(np.abs(validation[TARGET_COLUMN].to_numpy(dtype=float) - rounded).sum())
            trials.append({"lower": lower, "upper": upper, "shrinkage": shrinkage, "validation_sae": sae})
    selected = min(trials, key=lambda row: (row["validation_sae"], row["upper"] - row["lower"], -row["shrinkage"]))
    model = HierarchicalLevelCalibrator(selected["lower"], selected["upper"], selected["shrinkage"]).fit(internal)
    return model, {"trials": trials, "selected": selected, "inner_split": audit}


A2_CATEGORICAL = ("route", "hour", "dow", "day_type", "horizon_band", "state")
A2_NUMERIC = ("horizon_day", "b0", "b1", "b2", "component_gap", "origin_level_ratio")


@dataclass
class HourlyResidualCalibrator:
    config: dict

    def _features(self, data: pd.DataFrame) -> pd.DataFrame:
        result = data.copy()
        result["component_gap"] = result["b1"] - result["b0"]
        for column in A2_CATEGORICAL:
            result[column] = result[column].astype(str)
        return result[[*A2_CATEGORICAL, *A2_NUMERIC]]

    def _estimator(self, iterations: int):
        from catboost import CatBoostRegressor
        return CatBoostRegressor(
            loss_function=self.config["loss"], eval_metric=self.config["loss"],
            depth=self.config["depth"], learning_rate=self.config["learning_rate"],
            l2_leaf_reg=self.config["l2_leaf_reg"], iterations=iterations,
            random_seed=RANDOM_SEED, thread_count=4, task_type="CPU",
            allow_writing_files=False, verbose=False,
        )

    def fit(self, data: pd.DataFrame) -> "HourlyResidualCalibrator":
        from catboost import Pool
        train_mask, validation_mask, audit = fixed_origin_tuning_split(data, self.config["tuning_fraction"])
        features = self._features(data)
        target = data[TARGET_COLUMN].to_numpy(dtype=float) - data.b2.to_numpy(dtype=float)
        weights = 1.0 / data.duplicate_count.to_numpy(dtype=float)
        train_weights = 1.0 / data.loc[train_mask].groupby(["route", "date", "hour"])["date"].transform("size").to_numpy(dtype=float)
        with threadpool_limits(limits=4):
            probe = self._estimator(self.config["max_iterations"])
            probe.fit(
                Pool(features.loc[train_mask], target[train_mask], cat_features=list(A2_CATEGORICAL), weight=train_weights),
                eval_set=Pool(features.loc[validation_mask], target[validation_mask], cat_features=list(A2_CATEGORICAL)),
                early_stopping_rounds=self.config["early_stopping_rounds"], use_best_model=True,
            )
            self.iterations_ = max(1, int(probe.get_best_iteration()) + 1)
            self.model_ = self._estimator(self.iterations_)
            self.model_.fit(Pool(features, target, cat_features=list(A2_CATEGORICAL), weight=weights))
        self.fit_details_ = {"iterations": self.iterations_, "inner_split": audit}
        return self

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        residual = self.model_.predict(self._features(rows))
        return np.maximum(rows.b2.to_numpy(dtype=float) + residual, 0.0)


def _v4_features(frame: pd.DataFrame, *, component: str, mode: str, dow_override: int | None = None) -> tuple[pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    data = add_official_calendar_features(frame[["route", "date", "hour"]].copy())
    route_codes = {route: index for index, route in enumerate(MODELED_ROUTES)}
    data["route_code"] = data.route.map(route_codes).astype("int16")
    actual_dow = data.date.dt.dayofweek.astype("int8")
    data["dow"] = actual_dow if dow_override is None else np.int8(dow_override)
    data["is_weekend"] = (data["dow"].astype(int) >= 5).astype("int8")
    data["month"] = (data.date.dt.month - 1).astype("int8")
    data["week"] = (data.date.dt.isocalendar().week.astype(int) - 1).astype("int16")
    day = data.date.dt.dayofyear.to_numpy(dtype=float)
    data["day_of_year_sin"] = np.sin(2.0 * np.pi * day / 365.25)
    data["day_of_year_cos"] = np.cos(2.0 * np.pi * day / 365.25)
    if component == "calendar":
        data["route"] = data.route.astype(str)
        data["hour"] = data.hour.astype(str)
        data["dow"] = data.dow.astype(str)
        data["month"] = data.date.dt.month.astype(str)
        categorical = ["route", "hour", "dow", "month"]
        if mode == "seasonal_portable":
            categorical.remove("month")
        if mode == "day_type":
            data["day_type"] = official_day_type(data).astype(str)
            data["route_day_type"] = data["route"] + "_" + data["day_type"]
            data["hour_day_type"] = data["hour"] + "_" + data["day_type"]
            categorical.extend(["route_day_type", "hour_day_type"])
        numeric = ["is_weekend", "day_of_year_sin", "day_of_year_cos", *HOLIDAY_MODEL_COLUMNS]
    else:
        data["route_hour"] = (data.route_code * 24 + data.hour).astype("int16")
        data["route_dow"] = (data.route_code * 7 + data.dow.astype(int)).astype("int16")
        data["hour_dow"] = (data.dow.astype(int) * 24 + data.hour).astype("int16")
        categorical = list(BASE_INTERACTION_CATEGORICAL)
        if mode == "seasonal_portable":
            categorical = [name for name in categorical if name not in ("month", "week")]
        if mode == "day_type":
            day_type = official_day_type(data)
            codes = day_type.map({"workday": 0, "day_off": 1, "holiday": 2}).astype("int8")
            data["route_day_type"] = (data.route_code * 3 + codes).astype("int16")
            data["hour_day_type"] = (data.hour * 3 + codes).astype("int16")
            categorical.extend(["route_day_type", "hour_day_type"])
        numeric = list(INTERACTION_NUMERIC)
    return data[[*categorical, *numeric]], tuple(categorical), tuple(numeric)


@dataclass
class V4B2AblationModel:
    mode: str
    seed: int = RANDOM_SEED

    def fit(self, history: pd.DataFrame) -> "V4B2AblationModel":
        if self.mode not in ("seasonal_portable", "day_type"):
            raise ValueError("Unsupported B ablation")
        ordered = history[history.route.isin(MODELED_ROUTES)].sort_values(["route", "timestamp"], ignore_index=True).copy()
        self.history_end_ = pd.Timestamp(ordered.date.max())
        calendar_x, calendar_cat, calendar_num = _v4_features(ordered, component="calendar", mode=self.mode)
        preprocessing = ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), list(calendar_cat)),
            ("numeric", StandardScaler(), list(calendar_num)),
        ])
        self.calendar_ = Pipeline([
            ("preprocessing", preprocessing),
            ("regressor", HistGradientBoostingRegressor(
                **HGBT_FIXED_PARAMETERS, max_iter=220, max_leaf_nodes=31,
                random_state=self.seed, early_stopping="auto",
            )),
        ])
        interaction_x, interaction_cat, _ = _v4_features(ordered, component="interaction", mode=self.mode)
        age = (self.history_end_ - ordered.date).dt.days.to_numpy(dtype=float)
        weight = np.exp(-np.log(2.0) * age / INTERACTION_HALF_LIFE_DAYS)
        self.interaction_ = HistGradientBoostingRegressor(
            loss="squared_error", learning_rate=0.05, max_iter=300, max_leaf_nodes=31,
            min_samples_leaf=24, l2_regularization=1.0,
            categorical_features=list(interaction_cat), random_state=self.seed, early_stopping="auto",
        )
        with threadpool_limits(limits=4):
            self.calendar_.fit(calendar_x, ordered[TARGET_COLUMN].to_numpy(dtype=float))
            self.interaction_.fit(interaction_x, ordered[TARGET_COLUMN].to_numpy(dtype=float), sample_weight=weight)
        self.feature_manifest_ = {
            "mode": self.mode,
            "calendar_categorical": list(calendar_cat),
            "interaction_categorical": list(interaction_cat),
            "numeric": list(calendar_num),
            "working_weekend_rule": "mean of five Mon-Fri counterfactual dow predictions" if self.mode == "day_type" else "incumbent calendar only",
        }
        return self

    def _predict_component(self, rows: pd.DataFrame, component: str) -> np.ndarray:
        model = self.calendar_ if component == "calendar" else self.interaction_
        features, _, _ = _v4_features(rows, component=component, mode=self.mode)
        prediction = model.predict(features)
        if self.mode == "day_type":
            flags = add_official_calendar_features(rows[["date"]].copy())["is_working_weekend"].eq(1).to_numpy()
            if flags.any():
                counterfactual = []
                subset = rows.loc[flags]
                for dow in range(5):
                    alternate, _, _ = _v4_features(subset, component=component, mode=self.mode, dow_override=dow)
                    counterfactual.append(model.predict(alternate))
                prediction[flags] = np.mean(counterfactual, axis=0)
        return np.maximum(prediction, 0.0)

    def predict(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DataFrame:
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        if start_ts <= self.history_end_:
            raise ValueError("Prediction starts inside fitted history")
        grid = full_hourly_grid(start_ts, end_ts, ROUTES)
        supported = grid[grid.route.isin(MODELED_ROUTES)].copy()
        calendar = self._predict_component(supported, "calendar")
        interaction = self._predict_component(supported, "interaction")
        supported["prediction"] = np.maximum(
            ENSEMBLE_SCALE * (ENSEMBLE_CALENDAR_WEIGHT * calendar + ENSEMBLE_INTERACTION_WEIGHT * interaction), 0.0
        )
        result = grid.merge(supported[[*KEY_COLUMNS, "prediction"]], on=list(KEY_COLUMNS), how="left", validate="one_to_one")
        result["prediction"] = result.prediction.fillna(0.0)
        result["status"] = np.where(result.route.isin(MODELED_ROUTES), "ok", "cold_start_zero_baseline")
        return result


class HorizonBalancedDirectModel(ScoreV3Model):
    """D2: D1 with grid-only equal effective mass for horizons 1..61."""

    def _weights(self, data: pd.DataFrame) -> np.ndarray:
        weight = super()._weights(data)
        horizon = (data["_target_date"] - data["_origin"]).dt.days.astype(int)
        before = pd.Series(weight).groupby(horizon.to_numpy()).sum()
        target_mass = float(before.mean())
        scale = horizon.map({int(key): target_mass / float(value) for key, value in before.items()}).to_numpy(dtype=float)
        balanced = weight * scale
        after = pd.Series(balanced).groupby(horizon.to_numpy()).sum()
        self.horizon_weight_audit_ = {
            "rule": "inverse duplicate weight multiplied by mean_horizon_mass / horizon_mass; grid-only, no errors",
            "before": {str(int(k)): float(v) for k, v in before.items()},
            "after": {str(int(k)): float(v) for k, v in after.items()},
            "target_mass": target_mass,
        }
        return balanced

    def fit(self, history: pd.DataFrame, factors=None) -> "HorizonBalancedDirectModel":
        super().fit(history, factors=factors)
        self.fit_details_["horizon_weighting"] = self.horizon_weight_audit_
        return self
