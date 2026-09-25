import json
import unittest

import pandas as pd

from ml.data import full_hourly_grid
from ml.evaluation import _merge_actual_prediction, experiment_log_frame, slice_metrics


class ExperimentLogTests(unittest.TestCase):
    def test_log_keeps_hypothesis_decision_and_important_slices(self):
        report = {
            "experiments": [
                {
                    "experiment_id": "fold__candidate",
                    "hypothesis": "A testable hypothesis.",
                    "change": "candidate",
                    "information_mode": "operational",
                    "factor_groups": ["F01_official_calendar"],
                    "factor_coverage": None,
                    "model_schema_version": "test-v1",
                    "random_seed": 17,
                    "parameters": {"depth": 3},
                    "decision": "rejected",
                    "elapsed_seconds": 1.25,
                    "fold": {
                        "train_start": "2025-01-01",
                        "train_end": "2025-01-31",
                        "val_start": "2025-02-01",
                        "val_end": "2025-02-28",
                        "role": "model_selection",
                    },
                    "metrics": [
                        {
                            "slice": "overall",
                            "value": "all",
                            "rows": 2,
                            "sum_y": 10.0,
                            "sum_abs_error": 2.0,
                            "mae": 1.0,
                            "wape": 0.2,
                            "wape_score": 0.8,
                        },
                        {
                            "slice": "route",
                            "value": "1",
                            "rows": 2,
                            "sum_y": 10.0,
                            "sum_abs_error": 2.0,
                            "mae": 1.0,
                            "wape": 0.2,
                            "wape_score": 0.8,
                        },
                    ],
                }
            ]
        }

        result = experiment_log_frame(report)
        self.assertEqual(result.loc[0, "hypothesis"], "A testable hypothesis.")
        self.assertEqual(result.loc[0, "decision"], "rejected")
        self.assertEqual(result.loc[0, "random_seed"], 17)
        self.assertEqual(result.loc[0, "information_mode"], "operational")
        self.assertEqual(json.loads(result.loc[0, "factor_groups_json"]), ["F01_official_calendar"])
        self.assertEqual(json.loads(result.loc[0, "parameters_json"]), {"depth": 3})
        slices = json.loads(result.loc[0, "important_slices_json"])
        self.assertEqual(slices["route"]["1"]["wape_score"], 0.8)

    def test_61_day_holdout_has_exact_required_horizon_buckets(self):
        actual = full_hourly_grid("2025-09-01", "2025-10-31", routes=[1])
        actual["timestamp"] = actual["date"] + pd.to_timedelta(actual["hour"], unit="h")
        actual["boardings"] = 1
        predicted = actual[["route", "date", "hour"]].copy()
        predicted["prediction"] = 1.0
        predicted["status"] = "ok"

        merged = _merge_actual_prediction(actual, predicted)
        counts = merged.groupby("horizon_bucket", observed=True).size().to_dict()
        self.assertEqual(
            counts,
            {"days_1_7": 7 * 24, "days_8_30": 23 * 24, "days_31_61": 31 * 24},
        )
        metric_values = {
            metric["value"]
            for metric in slice_metrics(merged)
            if metric["slice"] == "horizon_bucket"
        }
        self.assertEqual(metric_values, {"days_1_7", "days_8_30", "days_31_61"})


if __name__ == "__main__":
    unittest.main()
