import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data import full_hourly_grid
from scripts.route50_adaptive import correct, switch_decision


CONFIG = json.loads(Path("ml/experiments/route50-adaptive.json").read_text())


class AdaptiveRoute50Tests(unittest.TestCase):
    def history(self, low_start=None):
        data = full_hourly_grid("2025-01-01", "2025-12-31", routes=(50,))
        data["boardings"] = 100
        if low_start:
            data.loc[data.date.ge(low_start) & data.date.dt.dayofweek.ge(5), "boardings"] = 10
        return data

    def test_high_level_never_changes_forecast_and_short_history_is_off(self):
        history = self.history()
        for origin in ("2025-01-01", "2025-01-15", "2025-05-26", "2025-11-01"):
            base = full_hourly_grid(origin, origin, routes=(5, 50))
            base["prediction"] = np.where(base.route.eq(5), 0., 100.3)
            result, decision, _ = correct(base, history, origin, CONFIG)
            self.assertFalse(decision["enabled"])
            pd.testing.assert_frame_equal(base, result)

    def test_decline_in_may_switches_without_september_date(self):
        history = self.history("2025-05-01")
        self.assertTrue(switch_decision(history, "2025-05-26", CONFIG)["enabled"])
        self.assertFalse(switch_decision(history, "2025-05-12", CONFIG)["enabled"])

    def test_one_weekend_or_one_weekday_decline_is_not_enough(self):
        history = self.history("2025-05-17")
        self.assertFalse(switch_decision(history, "2025-05-19", CONFIG)["enabled"])
        history = self.history("2025-05-01")
        history.loc[history.date.dt.dayofweek.eq(6), "boardings"] = 100
        self.assertFalse(switch_decision(history, "2025-05-26", CONFIG)["enabled"])

    def test_future_mutation_changes_neither_switch_nor_predictions(self):
        history = self.history("2025-05-01")
        base = full_hourly_grid("2025-05-26", "2025-07-25", routes=(5, 50))
        base["prediction"] = np.where(base.route.eq(5), 0., 100.3)
        left, decision, profile = correct(base, history, "2025-05-26", CONFIG)
        mutated = history.copy()
        mutated.loc[mutated.date.ge("2025-05-26"), "boardings"] = 1_000_000
        right, other_decision, other_profile = correct(base, mutated, "2025-05-26", CONFIG)
        self.assertEqual(decision, other_decision)
        pd.testing.assert_frame_equal(left, right)
        pd.testing.assert_frame_equal(profile, other_profile)
        self.assertLess(max(decision["recent_dates"]), "2025-05-26")

    def test_recovery_disables_switch(self):
        history = self.history("2025-05-01")
        self.assertTrue(switch_decision(history, "2025-05-26", CONFIG)["enabled"])
        history.loc[history.date.between("2025-05-31", "2025-06-01"), "boardings"] = 100
        self.assertFalse(switch_decision(history, "2025-06-02", CONFIG)["enabled"])

    def test_missing_whole_day_cannot_mimic_low_demand(self):
        history = self.history("2025-05-01")
        history = history[history.date.ne("2025-05-24")]
        with self.assertRaisesRegex(ValueError, "Incomplete historical"):
            switch_decision(history, "2025-05-26", CONFIG)

    def test_enabled_gate_preserves_working_saturday_holidays_and_other_routes(self):
        history = self.history("2025-10-01")
        base = full_hourly_grid("2025-11-01", "2025-12-31", routes=(5, 7, 50))
        base["prediction"] = np.where(base.route.eq(5), 0., 100.3)
        result, decision, _ = correct(base, history, "2025-11-01", CONFIG)
        self.assertTrue(decision["enabled"])
        self.assertEqual(int(result.prediction.ne(base.prediction).sum()), 17 * 24)
        protected = base.route.ne(50) | base.date.isin(pd.to_datetime(["2025-11-01", "2025-11-03", "2025-11-04", "2025-12-31"]))
        pd.testing.assert_frame_equal(base.loc[protected], result.loc[protected])


if __name__ == "__main__":
    unittest.main()
