import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.artifact import submission_preflight, write_submission
from ml.data import full_hourly_grid


class SubmissionTests(unittest.TestCase):
    def test_submission_preserves_template_keys_and_rounds_only_at_export(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            template = (
                full_hourly_grid("2025-11-01", "2025-12-31")
                .sample(frac=1, random_state=17)
                .reset_index(drop=True)
            )
            template["date"] = template["date"].dt.strftime("%Y-%m-%d")
            template["prediction"] = 0
            template_path = directory / "template.csv"
            output_path = directory / "submission.csv"
            template.to_csv(template_path, sep=";", index=False)

            prediction = full_hourly_grid("2025-11-01", "2025-12-31")
            prediction["prediction"] = 2.5
            write_submission(prediction, template_path, output_path)
            result = pd.read_csv(output_path, sep=";")
            self.assertEqual(list(result.columns), ["route", "date", "hour", "prediction"])
            self.assertEqual(len(result), 14_640)
            self.assertEqual(set(result.prediction), {3})
            self.assertTrue(
                result[["route", "date", "hour"]].equals(template[["route", "date", "hour"]])
            )
            preflight = submission_preflight(output_path, template_path)
            self.assertTrue(preflight["passed"])
            self.assertEqual(len(preflight["sha256"]), 64)
            self.assertEqual(preflight["checks"]["duplicate_keys"], 0)
            self.assertEqual(preflight["checks"]["date_min"], "2025-11-01")
            self.assertEqual(preflight["checks"]["date_max"], "2025-12-31")
            self.assertEqual(preflight["submission_scope"], "sample")
            self.assertIn("route_5_conflicts", preflight["contract_status"])

    def test_modeled_route_candidate_excludes_route_five_but_keeps_template_order(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            template = full_hourly_grid("2025-11-01", "2025-12-31")
            template["date"] = template["date"].dt.strftime("%Y-%m-%d")
            template["prediction"] = 0
            template_path = directory / "template.csv"
            output_path = directory / "submission-nine-routes.csv"
            template.to_csv(template_path, sep=";", index=False)

            prediction = full_hourly_grid("2025-11-01", "2025-12-31")
            prediction["prediction"] = 2.5
            write_submission(
                prediction,
                template_path,
                output_path,
                scope="modeled_routes",
            )
            result = pd.read_csv(output_path, sep=";")
            self.assertEqual(len(result), 13_176)
            self.assertNotIn(5, set(result.route))
            expected = template[template.route != 5].reset_index(drop=True)
            self.assertTrue(result[["route", "date", "hour"]].equals(expected[["route", "date", "hour"]]))

            preflight = submission_preflight(
                output_path,
                template_path,
                scope="modeled_routes",
            )
            self.assertTrue(preflight["passed"])
            self.assertFalse(preflight["checks"]["original_template_keys_and_order_exact"])
            self.assertEqual(preflight["submission_scope"], "modeled_routes")
            self.assertEqual(preflight["checks"]["expected_row_count"], 13_176)

    def test_preflight_rejects_changed_key_order(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            template = full_hourly_grid("2025-11-01", "2025-12-31")
            template["date"] = template["date"].dt.strftime("%Y-%m-%d")
            template["prediction"] = 0
            template_path = directory / "template.csv"
            output_path = directory / "submission.csv"
            template.to_csv(template_path, sep=";", index=False)
            changed = template.iloc[::-1].reset_index(drop=True)
            changed.to_csv(output_path, sep=";", index=False)

            preflight = submission_preflight(output_path, template_path)
            self.assertFalse(preflight["passed"])
            self.assertFalse(preflight["checks"]["template_keys_and_order_exact"])

    def test_preflight_reports_missing_key_column_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            template = full_hourly_grid("2025-11-01", "2025-12-31")
            template["date"] = template["date"].dt.strftime("%Y-%m-%d")
            template["prediction"] = 0
            template_path = directory / "template.csv"
            output_path = directory / "submission.csv"
            template.to_csv(template_path, sep=";", index=False)
            template.drop(columns="route").to_csv(output_path, sep=";", index=False)

            preflight = submission_preflight(output_path, template_path)
            self.assertFalse(preflight["passed"])
            self.assertFalse(preflight["checks"]["columns_exact"])
            self.assertFalse(preflight["checks"]["routes_valid"])


if __name__ == "__main__":
    unittest.main()
