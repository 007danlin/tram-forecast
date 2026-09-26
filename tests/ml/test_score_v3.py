import importlib.util
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.score_v3 import OriginSnapshot, ScoreV3Model, _source_features, score_v3_config


HAS_CATBOOST = importlib.util.find_spec("catboost") is not None


def synthetic_history(days=80):
    dates = pd.date_range("2025-01-01", periods=days)
    rows = []
    for date in dates:
        for hour in range(24):
            rows.append(
                {
                    "route": 7,
                    "date": date,
                    "hour": hour,
                    "boardings": 30 + hour + date.dayofweek * 2 + (date.dayofyear % 5),
                }
            )
    return pd.DataFrame(rows)


class ScoreV3Tests(unittest.TestCase):
    def test_source_feature_respects_publication_time_and_planned_end(self):
        targets = pd.DataFrame(
            {
                "route": [7, 50, 17, 7],
                "date": pd.to_datetime(["2025-07-10", "2025-08-06", "2025-07-10", "2025-08-07"]),
            }
        )
        active, unknown = _source_features(pd.Timestamp("2025-07-08"), targets)
        np.testing.assert_array_equal(active, [0, 0, 0, 0])
        active, unknown = _source_features(pd.Timestamp("2025-07-09"), targets)
        np.testing.assert_array_equal(active, [1, 1, 0, 0])
        np.testing.assert_array_equal(unknown, [1, 1, 0, 0])

    def test_future_target_mutation_does_not_change_origin_features(self):
        history = synthetic_history()
        origin = pd.Timestamp("2025-02-28")
        config = score_v3_config("daily", "test", iterations=2)
        original = history[history.date.le(origin)].copy()
        changed = history.copy()
        changed.loc[changed.date.gt(origin), "boardings"] = 999_999
        changed = changed[changed.date.le(origin)].copy()
        target = pd.DataFrame({"route": [7], "date": [origin + pd.Timedelta(days=20)]})
        left = OriginSnapshot(original, config).calendar_features(target, include_hour=False)
        right = OriginSnapshot(changed, config).calendar_features(target, include_hour=False)
        pd.testing.assert_frame_equal(left, right)

    def test_hourly_shares_are_nonnegative_and_normalized(self):
        history = synthetic_history()
        config = score_v3_config("daily", "test", iterations=2)
        snapshot = OriginSnapshot(history, config)
        target = pd.DataFrame(
            {
                "route": [7] * 48,
                "date": np.repeat(pd.to_datetime(["2025-03-22", "2025-03-23"]), 24),
                "hour": list(range(24)) * 2,
            }
        )
        shares, _ = snapshot.hourly_shares(target)
        self.assertTrue((shares >= 0).all())
        np.testing.assert_allclose(shares.reshape(2, 24).sum(axis=1), [1.0, 1.0])

    @unittest.skipUnless(HAS_CATBOOST, "Optional CatBoost dependency is unavailable")
    def test_daily_model_serialization_and_next_horizon(self):
        history = synthetic_history()
        config = score_v3_config(
            "daily",
            "test-fit",
            iterations=3,
            minimum_history=56,
            minimum_target_days=14,
            origin_step=28,
            inner_days=7,
        )
        model = ScoreV3Model(config).fit(history)
        before = model.predict("2025-03-22", "2025-03-23")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            joblib.dump(model, path)
            after = joblib.load(path).predict("2025-03-22", "2025-03-23")
        pd.testing.assert_frame_equal(before, after)
        self.assertTrue((before.loc[before.route.eq(5), "prediction"] == 0).all())
        self.assertEqual(len(before), 10 * 2 * 24)
        with self.assertRaises(ValueError):
            model.predict("2025-03-22", "2025-05-22")


if __name__ == "__main__":
    unittest.main()
