"""Models for the bounded score-improvement-v2 study; legacy names stay intact."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from ml.data import full_hourly_grid
from ml.factors import HOLIDAY_MODEL_COLUMNS, WEATHER_MODEL_COLUMNS, add_official_calendar_features
from ml.model import CALENDAR_NUMERIC_COLUMNS, HGBT_FIXED_PARAMETERS, _attach_weather, _calendar_features
from ml.settings import ROUTES, TARGET_COLUMN

SCHEMA = 'score-improvement-v2'
KINDS = ('profile', 'level', 'hgbt', 'catboost', 'blend', 'direct')
CAT_COLUMNS = ('route', 'hour', 'dow', 'day_type', 'route_hour', 'route_dow')
RAIN_COLUMNS = tuple(c for c in WEATHER_MODEL_COLUMNS if c in ('precipitation', 'is_wet', 'precipitation_6h'))


def normalize_score_config(raw):
    c = copy.deepcopy(raw)
    allowed = {'schema', 'id', 'kind', 'seed', 'threads', 'model_name', 'information_mode',
               'weather_columns', 'weather_groups', 'alignment', 'window', 'statistic', 'alpha',
               'half_life', 'max_iter', 'max_leaf_nodes', 'depth', 'l2_leaf_reg', 'iterations',
               'learning_rate', 'early_stopping_rounds', 'inner_days', 'components', 'weights',
               'origin_step', 'minimum_history', 'horizon'}
    if not isinstance(c, dict) or set(c) - allowed or c.get('schema') != SCHEMA or c.get('kind') not in KINDS:
        raise ValueError('Invalid score model config')
    kind = c['kind']
    c.setdefault('id', kind)
    c.setdefault('seed', 20250925)
    c.setdefault('threads', 4)
    if type(c['seed']) is not int or type(c['threads']) is not int or not 1 <= c['threads'] <= 4:
        raise ValueError('Invalid seed/thread budget')
    c.setdefault('weather_groups', [])
    if c['weather_groups'] not in ([], ['precipitation']):
        raise ValueError('Only the predeclared rain ablation is supported')
    c.setdefault('alignment', 'next_hour_accumulation_v2')
    if c['alignment'] != 'next_hour_accumulation_v2':
        raise ValueError('Score study requires buffered weather alignment')
    if kind == 'blend':
        from ml.experiment_config import normalize_config
        c['components'] = [normalize_config(x) for x in c['components']]
        w = np.asarray(c['weights'], dtype=float)
        if len(w) != len(c['components']) or len(w) < 2 or not np.isfinite(w).all() or (w <= 0).any() or not np.isclose(w.sum(), 1):
            raise ValueError('Blend requires positive weights summing to one')
        c['weather_groups'] = ['precipitation'] if any(x['weather_groups'] for x in c['components']) else []
    if kind in ('profile', 'level') and c['weather_groups']:
        raise ValueError('Profiles are calendar only')
    if kind == 'profile':
        if c.get('window') not in (28, 56) or c.get('statistic') not in ('median', 'exponential_mean'):
            raise ValueError('Invalid recent profile')
        if not 0 < c.get('alpha', 1) <= 1:
            raise ValueError('Invalid profile weight')
    for field in ('window', 'half_life', 'max_iter', 'max_leaf_nodes', 'depth', 'iterations', 'early_stopping_rounds', 'inner_days', 'origin_step', 'minimum_history', 'horizon'):
        if field in c and c[field] is not None and (type(c[field]) is not int or c[field] <= 0):
            raise ValueError(f'Invalid positive integer: {field}')
    derived = {'model_name': f'score_{kind}_v2',
               'information_mode': 'competition_retro' if c['weather_groups'] else 'operational',
               'weather_columns': list(RAIN_COLUMNS) if c['weather_groups'] else []}
    for k, v in derived.items():
        if k in c and c[k] != v:
            raise ValueError(f'Inconsistent {k}')
        c[k] = v
    return c


def score_config(kind, id, **kwargs):
    return normalize_score_config({'schema': SCHEMA, 'kind': kind, 'id': id, **kwargs})


def calendar(frame):
    data = _calendar_features(frame, include_official_calendar=True)
    # Weekday + official working/off status distinguishes shifted holidays/work Saturdays.
    data['day_type'] = data['is_day_off'].astype(str)
    return data


class RecentProfile:
    """Origin-frozen profile. Sparse weekday cells fall back to official day type."""
    def __init__(self, window=56, statistic='median'):
        self.window, self.statistic = window, statistic

    def fit(self, history):
        self.cutoff_ = history.date.max()
        data = calendar(history[history.date > self.cutoff_ - pd.Timedelta(days=self.window)])
        data['weight'] = 2. ** (-(self.cutoff_ - data.date).dt.days / 28.)
        self.tables_ = []
        for keys in (['route', 'hour', 'dow', 'day_type'], ['route', 'hour', 'day_type']):
            grouped = data.groupby(keys, sort=False)
            counts = grouped.date.nunique()
            if self.statistic == 'median':
                values = grouped[TARGET_COLUMN].median()
            else:
                weighted = data.assign(weighted=data[TARGET_COLUMN] * data.weight)
                values = weighted.groupby(keys).weighted.sum() / grouped.weight.sum()
            self.tables_.append((keys, values[counts >= 3].to_dict()))
        return self

    def values(self, frame, fallback):
        data = calendar(frame)
        result = np.full(len(data), np.nan)
        for keys, table in self.tables_:
            lookup = np.array([table.get(tuple(row), np.nan) for row in data[keys].itertuples(index=False, name=None)])
            result = np.where(np.isnan(result), lookup, result)
        return np.where(np.isnan(result), np.asarray(fallback, dtype=float), result)


def level_ratios(history):
    data = calendar(history)
    cutoff = data.date.max()
    daily = data.groupby(['route', 'day_type', 'date'], as_index=False)[TARGET_COLUMN].sum()
    recent = daily[daily.date > cutoff - pd.Timedelta(days=14)].groupby(['route', 'day_type'])[TARGET_COLUMN].agg(['mean', 'count'])
    previous = daily[daily.date.between(cutoff - pd.Timedelta(days=55), cutoff - pd.Timedelta(days=14))].groupby(['route', 'day_type'])[TARGET_COLUMN].agg(['mean', 'count'])
    ratios = {}
    for key in recent.index.intersection(previous.index):
        a, b = recent.loc[key], previous.loc[key]
        if a['count'] >= 3 and b['count'] >= 3 and b['mean'] > 0:
            ratios[key] = 1 + .5 * (np.clip(a['mean'] / b['mean'], .8, 1.2) - 1)
    return ratios


def cat_features(frame, factors=None, weather_columns=()):
    data = calendar(frame)
    data['route_hour'] = data.route.astype(str) + '_' + data.hour.astype(str)
    data['route_dow'] = data.route.astype(str) + '_' + data.dow.astype(str)
    if weather_columns:
        data = _attach_weather(data, factors, weather_columns)
    for name in CAT_COLUMNS:
        data[name] = data[name].astype(str)
    return data[[*CAT_COLUMNS, *CALENDAR_NUMERIC_COLUMNS, *HOLIDAY_MODEL_COLUMNS, *weather_columns]]


def history_weights(frame, cutoff, half_life):
    return np.ones(len(frame)) if half_life is None else 2. ** (-(cutoff - frame.date).dt.days.to_numpy() / half_life)


@dataclass
class ScoreModel:
    experiment_config: dict
    include_lags: bool = False
    include_official_calendar: bool = True
    max_iter: int = 220
    max_leaf_nodes: int = 31

    def __post_init__(self):
        self.experiment_config = normalize_score_config(self.experiment_config)
        self.name = self.experiment_config['model_name']
        self.information_mode = self.experiment_config['information_mode']
        self.selected_weather_columns = tuple(self.experiment_config['weather_columns'])
        self.include_weather = bool(self.selected_weather_columns)
        self.max_iter = self.experiment_config.get('max_iter', 220)
        self.max_leaf_nodes = self.experiment_config.get('max_leaf_nodes', 31)

    def _baseline(self, history, factors, cache):
        from ml.experiment_config import normalize_config
        config = {'id': 'W00', 'weather_groups': []}
        if self.experiment_config['seed'] != 20250925:
            config['seed'] = self.experiment_config['seed']
        return fit_component(normalize_config(config), history, factors, cache)

    def fit(self, history, factors=None, _cache=None):
        from ml.model import build_hgbt_model
        c = self.experiment_config
        cache = {} if _cache is None else _cache
        if history.empty or history.date.max() > pd.Timestamp('2025-10-31'):
            raise ValueError('Empty or forbidden target history')
        self.history_end_, self.history_start_ = history.date.max(), history.date.min()
        totals = history.groupby('route')[TARGET_COLUMN].sum()
        self.supported_routes_ = tuple(int(x) for x in totals[totals > 0].index)
        training = history[history.route.isin(self.supported_routes_)].copy()
        self.fit_details_ = {'train_start': str(self.history_start_.date()), 'train_end': str(self.history_end_.date())}
        kind = c['kind']
        with threadpool_limits(limits=c['threads']):
            if kind == 'blend':
                self.components_ = [fit_component(x, history, factors, cache) for x in c['components']]
            elif kind in ('profile', 'level'):
                self.baseline_ = self._baseline(history, factors, cache)
                if kind == 'profile':
                    self.profile_ = RecentProfile(c['window'], c['statistic']).fit(history)
                else:
                    self.ratios_ = level_ratios(history)
            elif kind == 'hgbt':
                if c.get('window'):
                    training = training[training.date > self.history_end_ - pd.Timedelta(days=c['window'])]
                features = calendar(training)
                categories = ['route', 'hour', 'dow']
                numeric = [*CALENDAR_NUMERIC_COLUMNS, *HOLIDAY_MODEL_COLUMNS]
                self.feature_columns_ = categories + numeric
                preprocess = ColumnTransformer([('categorical', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categories),
                                                ('numeric', StandardScaler(), numeric)])
                split = self.history_end_ - pd.Timedelta(days=c.get('inner_days', 28))
                inner = (training.date <= split).to_numpy()
                iterations = self.max_iter
                if inner.any() and (~inner).any():
                    encoder = clone(preprocess)
                    x = encoder.fit_transform(features.loc[inner])
                    xv = encoder.transform(features.loc[~inner])
                    probe = HistGradientBoostingRegressor(**HGBT_FIXED_PARAMETERS, max_iter=self.max_iter,
                        max_leaf_nodes=self.max_leaf_nodes, random_state=c['seed'], early_stopping=True)
                    probe.fit(x, training.loc[inner, TARGET_COLUMN],
                        sample_weight=history_weights(training.loc[inner], split, c.get('half_life')),
                        X_val=xv, y_val=training.loc[~inner, TARGET_COLUMN])
                    iterations = int(probe.n_iter_)
                self.pipeline_ = Pipeline([('preprocessing', preprocess), ('regressor', HistGradientBoostingRegressor(
                    **HGBT_FIXED_PARAMETERS, max_iter=iterations, max_leaf_nodes=self.max_leaf_nodes, random_state=c['seed'], early_stopping=False))])
                self.pipeline_.fit(features, training[TARGET_COLUMN], regressor__sample_weight=history_weights(training, self.history_end_, c.get('half_life')))
                self.fit_details_['iterations'] = int(self.pipeline_['regressor'].n_iter_)
                self.fit_details_['inner_train_end'] = str(split.date())
            elif kind in ('catboost', 'direct'):
                self._fit_cat(training, history, factors)
        return self

    def _cat_estimator(self, iterations):
        from catboost import CatBoostRegressor
        c = self.experiment_config
        return CatBoostRegressor(loss_function='MAE', learning_rate=c.get('learning_rate', .05), depth=c.get('depth', 6),
            l2_leaf_reg=c.get('l2_leaf_reg', 3), iterations=iterations, random_seed=c['seed'], thread_count=c['threads'],
            task_type='CPU', allow_writing_files=False, verbose=False)

    def _direct_training(self, history, factors):
        c = self.experiment_config
        parts = []
        # Each target row can appear at multiple origins; no target later than cutoff is used.
        first = history.date.min() + pd.Timedelta(days=c.get('minimum_history', 56) - 1)
        for cutoff in pd.date_range(first, history.date.max() - pd.Timedelta(days=1), freq=f"{c.get('origin_step', 14)}D"):
            past = history[history.date <= cutoff]
            targets = history[history.date.between(cutoff + pd.Timedelta(days=1), min(cutoff + pd.Timedelta(days=61), self.history_end_))].copy()
            if targets.empty:
                continue
            features = cat_features(targets, factors, self.selected_weather_columns)
            # Historical fallback also uses past-only route/hour medians.
            fallback = past.groupby(['route', 'hour'])[TARGET_COLUMN].median().to_dict()
            backup = np.array([fallback.get((r, h), 0.) for r, h in zip(targets.route, targets.hour)])
            features['recent_profile'] = RecentProfile().fit(past).values(targets, backup)
            features['horizon_day'] = (targets.date - cutoff).dt.days.to_numpy()
            features['_date'] = targets.date.to_numpy()
            features['_origin'] = cutoff
            features['_y'] = targets[TARGET_COLUMN].to_numpy()
            parts.append(features)
        if not parts:
            raise ValueError('Insufficient history for historical direct origins')
        return pd.concat(parts, ignore_index=True)

    def _fit_cat(self, training, history, factors):
        from catboost import Pool
        c = self.experiment_config
        if c['kind'] == 'direct':
            data = self._direct_training(training, factors)
            dates, target = data.pop('_date'), data.pop('_y').to_numpy(float)
            origins = data.pop('_origin')
            features = data
        else:
            features = cat_features(training, factors, self.selected_weather_columns)
            dates, target = training.date.reset_index(drop=True), training[TARGET_COLUMN].to_numpy(float)
        self.feature_columns_ = list(features.columns)
        split = self.history_end_ - pd.Timedelta(days=c.get('inner_days', 28))
        inner = (dates <= split).to_numpy()
        validation = ~inner
        if c['kind'] == 'direct':
            # Internal validation profiles must also be frozen before its cutoff.
            validation &= (origins <= split).to_numpy()
        iterations = c.get('iterations')
        def weights(mask, cutoff):
            selected = features.loc[mask]
            ds = dates.loc[mask]
            w = history_weights(pd.DataFrame({'date': ds}), cutoff, c.get('half_life'))
            if c['kind'] == 'direct':
                # Normalize target duplication separately inside each temporal partition.
                keys = pd.DataFrame({'route': selected.route.to_numpy(), 'hour': selected.hour.to_numpy(), 'date': ds.to_numpy()})
                w /= keys.groupby(['route', 'hour', 'date']).date.transform('size').to_numpy()
            return w
        if iterations is None:
            if not inner.any() or not validation.any():
                raise ValueError('No inner temporal train/validation split')
            probe = self._cat_estimator(c.get('max_iter', 1500))
            probe.fit(Pool(features.loc[inner], target[inner], cat_features=list(CAT_COLUMNS), weight=weights(inner, split)),
                      eval_set=Pool(features.loc[validation], target[validation], cat_features=list(CAT_COLUMNS), weight=weights(validation, self.history_end_)),
                      early_stopping_rounds=c.get('early_stopping_rounds', 100), use_best_model=True)
            iterations = max(1, int(probe.get_best_iteration()) + 1)
        self.fit_details_.update(iterations=iterations, inner_train_end=str(split.date()),
                                 inner_validation_start=str((split + pd.Timedelta(days=1)).date()), training_rows=len(features))
        all_rows = np.ones(len(features), dtype=bool)
        self.estimator_ = self._cat_estimator(iterations)
        self.estimator_.fit(Pool(features, target, cat_features=list(CAT_COLUMNS), weight=weights(all_rows, self.history_end_)))
        if c['kind'] == 'direct':
            self.profile_ = RecentProfile().fit(history)
            self.direct_fallback_ = history.groupby(['route', 'hour'])[TARGET_COLUMN].median().to_dict()

    def predict(self, start, end, factors=None):
        if pd.Timestamp(start) <= self.history_end_:
            raise ValueError('Prediction must start after fitted history')
        c = self.experiment_config
        grid = full_hourly_grid(start, end)
        grid['timestamp'] = grid.date + pd.to_timedelta(grid.hour, unit='h')
        with threadpool_limits(limits=c['threads']):
            if c['kind'] == 'blend':
                result = np.zeros(len(grid))
                for w, component in zip(c['weights'], self.components_):
                    p = component.predict(start, end, factors=factors)
                    if not p[['route', 'date', 'hour']].equals(grid[['route', 'date', 'hour']]):
                        raise ValueError('Component grid mismatch')
                    result += w * p.prediction.to_numpy()
            elif c['kind'] in ('profile', 'level'):
                baseline = self.baseline_.predict(start, end, factors=factors).prediction.to_numpy()
                if c['kind'] == 'profile':
                    alpha = c.get('alpha', 1.)
                    result = (1 - alpha) * baseline + alpha * self.profile_.values(grid, baseline)
                else:
                    frame = calendar(grid)
                    result = baseline * np.array([self.ratios_.get((r, t), 1.) for r, t in zip(frame.route, frame.day_type)])
            elif c['kind'] == 'hgbt':
                result = self.pipeline_.predict(calendar(grid))
            else:
                features = cat_features(grid, factors, self.selected_weather_columns)
                if c['kind'] == 'direct':
                    if (pd.Timestamp(end) - self.history_end_).days > 61:
                        raise ValueError('Direct model supports only horizons 1..61')
                    backup = [self.direct_fallback_.get((r, h), 0.) for r, h in zip(grid.route, grid.hour)]
                    features['recent_profile'] = self.profile_.values(grid, backup)
                    features['horizon_day'] = (grid.date - self.history_end_).dt.days.to_numpy()
                result = self.estimator_.predict(features)
        grid['prediction'] = np.where(grid.route.isin(self.supported_routes_), np.maximum(result, 0), 0.)
        grid['status'] = np.where(grid.route.isin(self.supported_routes_), 'ok', 'cold_start_zero_baseline')
        return grid


def fit_component(config, history, factors, cache):
    from ml.model import build_hgbt_model
    key = json.dumps(config, sort_keys=True)
    if key not in cache:
        model = build_hgbt_model(config['model_name'], config)
        if isinstance(model, ScoreModel):
            model.fit(history, factors, _cache=cache)
        else:
            model.fit(history, factors)
        cache[key] = model
    return cache[key]
