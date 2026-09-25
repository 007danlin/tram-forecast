import json
import unittest

from ml.evaluation import experiment_log_frame


class ExperimentLogTests(unittest.TestCase):
    def test_log_keeps_hypothesis_decision_and_important_slices(self):
        report = {
            "experiments": [
                {
                    "experiment_id": "fold__candidate",
                    "hypothesis": "A testable hypothesis.",
                    "change": "candidate",
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
        self.assertEqual(json.loads(result.loc[0, "parameters_json"]), {"depth": 3})
        slices = json.loads(result.loc[0, "important_slices_json"])
        self.assertEqual(slices["route"]["1"]["wape_score"], 0.8)


if __name__ == "__main__":
    unittest.main()
