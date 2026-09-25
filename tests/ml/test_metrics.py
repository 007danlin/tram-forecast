import unittest

from ml.metrics import regression_metrics, round_submission_predictions


class MetricTests(unittest.TestCase):
    def test_submission_rounding_matches_documented_half_up_policy(self):
        result = round_submission_predictions([0.49, 0.5, 1.49, 1.5, 2.51])
        self.assertEqual(result.tolist(), [0, 1, 1, 2, 3])

    def test_global_wape_score(self):
        result = regression_metrics([10, 20, 0, 30], [8, 25, 1, 26])
        self.assertEqual(result["rows"], 4)
        self.assertEqual(result["sum_y"], 60.0)
        self.assertAlmostEqual(result["sum_abs_error"], 12.0)
        self.assertAlmostEqual(result["wape"], 0.2)
        self.assertAlmostEqual(result["wape_score"], 0.8)

    def test_zero_demand_score_is_null(self):
        result = regression_metrics([0, 0], [1, 0])
        self.assertIsNone(result["wape"])
        self.assertIsNone(result["wape_score"])
        self.assertEqual(result["mae"], 0.5)

    def test_negative_values_are_rejected(self):
        with self.assertRaises(ValueError):
            regression_metrics([1], [-1])

    def test_submission_rounding_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            round_submission_predictions([1.0, float("nan")])


if __name__ == "__main__":
    unittest.main()
