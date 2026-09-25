import unittest

import pandas as pd

from ml.baselines import ComparableWeeksMedianBaseline, PreviousWeekdayBaseline
from ml.data import full_hourly_grid


def history_frame(start="2025-01-01", end="2025-02-28"):
    frame = full_hourly_grid(start, end)
    frame["timestamp"] = frame["date"] + pd.to_timedelta(frame["hour"], unit="h")
    frame["boardings"] = frame["route"] * 10 + frame["hour"] + frame["date"].dt.dayofweek
    frame.loc[frame.route == 5, "boardings"] = 0
    return frame


class BaselineTests(unittest.TestCase):
    def test_previous_weekday_uses_only_fitted_history(self):
        model = PreviousWeekdayBaseline().fit(history_frame())
        prediction = model.predict("2025-03-01", "2025-03-01")
        row = prediction[(prediction.route == 7) & (prediction.hour == 8)].iloc[0]
        self.assertEqual(row.prediction, 7 * 10 + 8 + 5)

    def test_route_five_is_explicit_cold_start(self):
        model = ComparableWeeksMedianBaseline().fit(history_frame())
        prediction = model.predict("2025-03-01", "2025-03-01")
        route = prediction[prediction.route == 5]
        self.assertTrue((route.prediction == 0).all())
        self.assertEqual(set(route.status), {"cold_start_zero_baseline"})


if __name__ == "__main__":
    unittest.main()
