import unittest

import numpy as np
import pandas as pd

from ml.data import full_hourly_grid
from scripts.route50_weekends import apply_profile, calendar, fit_profile, weekend_mask


class Route50WeekendsTests(unittest.TestCase):
    def history(self):
        data = full_hourly_grid("2025-09-01", "2025-11-30", routes=(50,))
        data["boardings"] = 1 + data.hour
        return data

    def test_future_targets_and_outside_window_do_not_affect_profile(self):
        data = self.history()
        profile, audit = fit_profile(data, "2025-11-01", 28)
        changed = data.copy()
        changed.loc[changed.date.ge("2025-11-01") | changed.date.lt("2025-10-04"), "boardings"] = 999999
        other, _ = fit_profile(changed, "2025-11-01", 28)
        pd.testing.assert_frame_equal(profile, other)
        self.assertLess(max(audit["dates_used"]), "2025-11-01")
        # A genuine large observation inside the window remains in the mean.
        changed.loc[changed.date.eq("2025-10-04") & changed.hour.eq(12), "boardings"] += 400
        with_peak, _ = fit_profile(changed, "2025-11-01", 28)
        self.assertAlmostEqual(float(with_peak.query("dow == 5 and hour == 12").profile.iloc[0]), 113.)

    def test_working_saturday_holidays_and_other_routes_unchanged(self):
        base = full_hourly_grid("2025-11-01", "2025-12-31", routes=(5, 7, 50))
        base["prediction"] = np.where(base.route.eq(5), 0., 100.4)
        profile, _ = fit_profile(self.history(), "2025-11-01", 56)
        result = apply_profile(base, profile, .5)
        mask = weekend_mask(base)
        pd.testing.assert_frame_equal(base.loc[~mask], result.loc[~mask])
        np.testing.assert_allclose(result.loc[mask, "prediction"],
                                   (100.4 + result.loc[mask, "hour"] + 1) / 2)
        kinds = calendar(base[base.route.eq(50)]).groupby("date").day_type.first()
        self.assertEqual(kinds.loc["2025-11-01"], "working_weekend")
        self.assertEqual(kinds.loc["2025-11-03"], "transferred_day_off")
        self.assertEqual(kinds.loc["2025-11-04"], "public_holiday")
        self.assertEqual(kinds.loc["2025-12-31"], "transferred_day_off")
        self.assertEqual(int(mask.sum()), 17 * 24)

    def test_missing_hours_are_not_treated_as_observed_zeros(self):
        data = self.history()
        data = data[~(data.date.eq("2025-10-04") & data.hour.eq(12))]
        with self.assertRaisesRegex(ValueError, "complete observed"):
            fit_profile(data, "2025-11-01", 28)


if __name__ == "__main__":
    unittest.main()
