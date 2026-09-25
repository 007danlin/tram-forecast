import unittest

import numpy as np
import pandas as pd

from ml.data import full_hourly_grid
from ml.model import HourlyGradientBoostingModel, make_training_features


def synthetic_history():
    frame = full_hourly_grid("2025-01-01", "2025-02-28")
    frame["timestamp"] = frame["date"] + pd.to_timedelta(frame["hour"], unit="h")
    frame["boardings"] = (
        20
        + frame["route"] * 2
        + frame["hour"] * 3
        + np.where(frame["date"].dt.dayofweek >= 5, -10, 10)
    ).clip(lower=0)
    frame.loc[frame.route == 5, "boardings"] = 0
    return frame


class ModelTests(unittest.TestCase):
    def test_lag_features_start_after_four_weeks(self):
        features, target = make_training_features(synthetic_history(), include_lags=True)
        self.assertFalse(features.isna().any().any())
        self.assertEqual(len(features), len(target))
        self.assertIn("lag_28d", features)

    def test_recursive_forecast_is_complete_and_nonnegative(self):
        model = HourlyGradientBoostingModel(include_lags=True, max_iter=10, max_leaf_nodes=15).fit(synthetic_history())
        prediction = model.predict("2025-03-01", "2025-03-08")
        self.assertEqual(len(prediction), 10 * 8 * 24)
        self.assertFalse(prediction.prediction.isna().any())
        self.assertTrue((prediction.prediction >= 0).all())
        self.assertEqual(set(prediction[prediction.route == 5].status), {"cold_start_zero_baseline"})


if __name__ == "__main__":
    unittest.main()
