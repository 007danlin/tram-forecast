import unittest

import numpy as np
import pandas as pd

from ml.score_v4 import (
    HierarchicalLevelCalibrator,
    HorizonBalancedDirectModel,
    _v4_features,
    attach_origin_features,
    internal_origins,
    origin_grid_audit,
    fixed_origin_tuning_split,
)
from ml.score_v3 import score_v3_config
from ml.score_v4_metrics import summarize_v4
from ml.score_v41 import project_shape
from ml.chronos_smoke import calendar_frame, hourly_from_daily
from ml.chronos_v4 import _n1_frames, _n2_frames
from ml.stats_v4 import _c1_input, _c2_input
from ml.factors import add_official_calendar_features


class ScoreV4Tests(unittest.TestCase):
    def test_v41_shape_projection_preserves_float_daily_volume_and_ignores_targets(self):
        keys = {
            "fold": ["S1"] * 4, "route": [7] * 4,
            "date": pd.to_datetime(["2025-05-01"] * 4), "hour": [0, 1, 2, 3],
            "horizon_day": [1] * 4, "status": ["ok"] * 4,
        }
        baseline = pd.DataFrame({**keys, "boardings": [1, 2, 3, 4], "prediction": [10., 20., 30., 40.]})
        shape = pd.DataFrame({**keys, "boardings": [1, 2, 3, 4], "prediction": [1., 1., 2., 6.]})
        projected = project_shape(baseline, shape)
        self.assertAlmostEqual(projected.prediction.sum(), baseline.prediction.sum())
        np.testing.assert_allclose(projected.prediction, [10., 10., 20., 60.])
        changed_shape = shape.copy(); changed_baseline = baseline.copy()
        changed_shape["boardings"] = changed_baseline["boardings"] = [999999, 0, 999999, 0]
        np.testing.assert_array_equal(projected.prediction, project_shape(changed_baseline, changed_shape).prediction)

    def test_v41_shape_projection_groups_folds_and_falls_back_on_zero_shape(self):
        baseline = pd.DataFrame({
            "fold": ["S1", "S1", "S2", "S2"], "route": [5] * 4,
            "date": pd.to_datetime(["2025-05-01"] * 2 + ["2025-05-01"] * 2),
            "hour": [0, 1, 0, 1], "boardings": [0] * 4,
            "prediction": [0., 0., 30., 70.], "status": ["ok"] * 4,
            "horizon_day": [1, 1, 1, 1],
        })
        shape = baseline.copy(); shape["prediction"] = [0., 0., 1., 1.]
        result = project_shape(baseline, shape)
        np.testing.assert_array_equal(result.prediction, [0., 0., 50., 50.])

    def test_five_day_origins_cover_multiple_weekdays(self):
        history = pd.DataFrame({"date": pd.date_range("2025-01-01", "2025-04-30")})
        config = {"origin_step_days": 5, "minimum_history_days": 60, "minimum_target_days": 14, "horizon_days": 61}
        origins = internal_origins(history, config)
        audit = origin_grid_audit(origins, 61, history.date.max())
        self.assertEqual(audit["represented_origin_dow"], list(range(7)))
        self.assertEqual(sum(audit["origin_dow_counts"].values()), len(origins))

    def test_origin_features_ignore_future_targets(self):
        rows = []
        for date in pd.date_range("2025-01-01", "2025-04-30"):
            rows.append({"route": 7, "date": date, "hour": 0, "boardings": 100 + date.dayofweek})
        history = pd.DataFrame(rows)
        target = pd.DataFrame({"route": [7], "date": [pd.Timestamp("2025-04-01")], "hour": [0], "horizon_day": [1]})
        left = attach_origin_features(target, history, down=0.9, up=1.1)
        changed = history.copy()
        changed.loc[changed.date.gt("2025-03-31"), "boardings"] = 999999
        right = attach_origin_features(target, changed, down=0.9, up=1.1)
        pd.testing.assert_frame_equal(left, right)

    def test_tuning_training_targets_are_available_at_validation_origin(self):
        rows = []
        for origin in pd.date_range("2025-03-01", "2025-04-01", freq="5D"):
            for horizon in range(1, 62):
                rows.append({"origin": origin, "date": origin + pd.Timedelta(days=horizon)})
        data = pd.DataFrame(rows)
        train, validation, audit = fixed_origin_tuning_split(data, .25)
        cutoff = pd.Timestamp(audit["origin"])
        self.assertTrue(data.loc[train, "date"].le(cutoff).all())
        self.assertEqual(data.loc[validation, "origin"].nunique(), 1)
        self.assertFalse(set(data.loc[train, "date"]) & set(data.loc[validation, "date"]))

    def test_daily_metrics_sum_rounded_hours(self):
        frame = pd.DataFrame({
            "route": [7, 7], "date": pd.to_datetime(["2025-05-01"] * 2),
            "hour": [0, 1], "boardings": [1, 1], "prediction": [.49, .49],
            "fold": ["S1", "S1"], "horizon_day": [1, 1],
        })
        self.assertEqual(summarize_v4(frame)["daily"]["absolute_error"], 2)

    def test_large_shrinkage_returns_no_level_correction(self):
        frame = pd.DataFrame({
            "route": [7], "day_type": ["workday"], "state": ["stable"],
            "b2": [100.], "boardings": [120.], "duplicate_count": [1.],
        })
        model = HierarchicalLevelCalibrator(.75, 1.25, 10000.).fit(frame)
        np.testing.assert_array_equal(model.predict_factor(frame), [1.])

    def test_statistical_and_neural_inputs_ignore_future_targets(self):
        dates = pd.date_range("2025-01-01", "2025-04-01")
        frame = pd.MultiIndex.from_product([[7], dates, range(24)], names=["route", "date", "hour"]).to_frame(index=False)
        frame["boardings"] = frame.hour * 10 + frame.date.dt.dayofweek
        changed = frame.copy()
        cutoff = pd.Timestamp("2025-03-01")
        changed.loc[changed.date.gt(cutoff), "boardings"] = 999999
        for callback in (_c1_input, _c2_input):
            pd.testing.assert_frame_equal(callback(frame, cutoff), callback(changed, cutoff))
        for callback in (_n1_frames, _n2_frames):
            left = callback(frame, cutoff, cutoff + pd.Timedelta(days=1), pd.Timestamp("2025-05-01"))
            right = callback(changed, cutoff, cutoff + pd.Timedelta(days=1), pd.Timestamp("2025-05-01"))
            for original, modified in zip(left, right):
                pd.testing.assert_frame_equal(original, modified)

    def test_daily_distribution_uses_only_forecast_shape(self):
        shape = pd.DataFrame({"route": [7] * 24, "date": pd.to_datetime(["2025-05-01"] * 24),
                              "hour": list(range(24)), "prediction": [0.] * 24, "boardings": [1.] * 24})
        daily = pd.DataFrame({"route": [7], "date": pd.to_datetime(["2025-05-01"]), "daily_prediction": [240.]})
        first = hourly_from_daily(daily, shape)
        shape["boardings"] *= 9999
        second = hourly_from_daily(daily, shape)
        np.testing.assert_array_equal(first.prediction, second.prediction)
        np.testing.assert_array_equal(first.prediction, np.full(24, 10.))

    def test_neural_calendar_matches_official_calendar_for_full_year(self):
        dates = pd.date_range("2025-01-01", "2025-12-31")
        actual = calendar_frame(dates)
        expected = add_official_calendar_features(pd.DataFrame({"date": dates}))
        for name in ("is_day_off", "is_public_holiday"):
            np.testing.assert_array_equal(actual[name], expected[name])
        self.assertEqual(actual.loc[dates == pd.Timestamp("2025-11-01"), "is_day_off"].iloc[0], 0)

    def test_hierarchical_calibrator_uses_shrunk_factor(self):
        frame = pd.DataFrame({
            "route": [7] * 8,
            "day_type": ["workday"] * 8,
            "state": ["stable"] * 8,
            "b2": [100.0] * 8,
            "boardings": [120.0] * 8,
            "duplicate_count": [1.0] * 8,
        })
        model = HierarchicalLevelCalibrator(0.75, 1.25, 10.0).fit(frame)
        factors = model.predict_factor(frame)
        self.assertTrue(np.all(factors > 1.0))
        self.assertTrue(np.all(factors <= 1.25))

    def test_b_ablation_feature_changes_are_isolated(self):
        rows = pd.DataFrame({
            "route": [7, 7],
            "date": pd.to_datetime(["2025-10-25", "2025-11-01"]),
            "hour": [8, 8],
        })
        seasonal, seasonal_cat, _ = _v4_features(rows, component="interaction", mode="seasonal_portable")
        self.assertNotIn("month", seasonal_cat)
        self.assertNotIn("week", seasonal_cat)
        day_type, day_type_cat, _ = _v4_features(rows, component="interaction", mode="day_type")
        self.assertIn("month", day_type_cat)
        self.assertIn("week", day_type_cat)
        self.assertIn("route_day_type", day_type.columns)
        self.assertIn("hour_day_type", day_type.columns)

    def test_horizon_balancing_equalizes_grid_mass_without_errors(self):
        config = score_v3_config(
            "direct", "test-D2", seed=20250925, threads=1, loss="MAE",
            target_transform="raw", origin_step=5,
            use_detected_regime=False, use_source_regimes=False,
        )
        model = HorizonBalancedDirectModel(config)
        model.history_end_ = pd.Timestamp("2025-06-30")
        data = pd.DataFrame({
            "_duplicate_count": [1.0, 2.0, 4.0, 1.0, 2.0, 4.0],
            "_origin": pd.to_datetime(["2025-01-01"] * 6),
            "_target_date": pd.to_datetime([
                "2025-01-02", "2025-01-02", "2025-01-03",
                "2025-01-03", "2025-01-04", "2025-01-04",
            ]),
            # D2 must not inspect labels/errors when constructing the weights.
            "_y": [0.0, 999999.0, 1.0, 500000.0, 2.0, 250000.0],
        })
        weights = model._weights(data)
        horizon = (data["_target_date"] - data["_origin"]).dt.days
        masses = pd.Series(weights).groupby(horizon.to_numpy()).sum().to_numpy()
        self.assertTrue(np.allclose(masses, masses[0]))
        changed = data.copy()
        changed["_y"] *= -123.0
        self.assertTrue(np.allclose(weights, model._weights(changed)))


if __name__ == "__main__":
    unittest.main()
