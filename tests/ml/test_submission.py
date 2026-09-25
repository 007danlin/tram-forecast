import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.artifact import write_submission
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


if __name__ == "__main__":
    unittest.main()
