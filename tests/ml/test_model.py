import unittest

import numpy as np
import pandas as pd

from ml.data import full_hourly_grid
from ml.model import (
    CalendarInteractionEnsembleModel,
    HourlyGradientBoostingModel,
    NativeInteractionGradientBoostingModel,
    make_training_features,
)


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

    def test_interaction_component_is_complete_and_keeps_route_five_out_of_scope(self):
        model = NativeInteractionGradientBoostingModel(max_iter=10, max_leaf_nodes=15).fit(
            synthetic_history()
        )
        prediction = model.predict("2025-03-01", "2025-03-02")
        self.assertEqual(len(prediction), 10 * 2 * 24)
        self.assertFalse(prediction.prediction.isna().any())
        self.assertTrue((prediction.prediction >= 0).all())
        self.assertNotIn(5, model.supported_routes_)

    def test_ensemble_combines_raw_predictions_before_rounding(self):
        keys = full_hourly_grid("2025-03-01", "2025-03-01", routes=[1]).iloc[:2].copy()
        calendar = keys.copy()
        calendar["prediction"] = [10.0, 20.0]
        calendar["status"] = "ok"
        interaction = keys.copy()
        interaction["prediction"] = [30.0, 40.0]
        interaction["status"] = "ok"

        class FixedModel:
            def __init__(self, frame):
                self.frame = frame

            def predict(self, start, end):
                return self.frame.copy()

        model = CalendarInteractionEnsembleModel()
        model.calendar_model_ = FixedModel(calendar)
        model.interaction_model_ = FixedModel(interaction)
        prediction = model.predict("2025-03-01", "2025-03-01")
        expected = 0.96 * (0.425 * calendar.prediction + 0.575 * interaction.prediction)
        np.testing.assert_allclose(prediction.prediction, expected)


if __name__ == "__main__":
    unittest.main()
