import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from ml.data import full_hourly_grid
from ml.cli import command_train
from ml.qa import apply_training_mask, history_drop_candidates, load_training_mask, training_mask_summary


def write_mask(directory: Path, *, start="2025-01-02 01:00:00", end="2025-01-02 03:00:00") -> Path:
    path = directory / "mask.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "tramflow-training-mask-v1",
                "mask_id": "synthetic-mask-v1",
                "timestamp_basis": "organizer_tran_date_time_naive",
                "timezone": "unconfirmed_organizer_local_time",
                "rules": [
                    {
                        "rule_id": "synthetic-route-1-window",
                        "route": 1,
                        "start": start,
                        "end": end,
                        "reason_code": "technological_validation",
                        "source_ref": "synthetic-test-only",
                        "verification_status": "verified",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class TrainingMaskTests(unittest.TestCase):
    def test_mask_preserves_target_and_marks_half_open_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            mask = load_training_mask(write_mask(Path(directory)))
            frame = full_hourly_grid("2025-01-02", "2025-01-02", routes=[1, 7])
            frame["timestamp"] = frame["date"] + pd.to_timedelta(frame["hour"], unit="h")
            frame["boardings"] = 10

            marked = apply_training_mask(frame, mask)
            excluded = marked[~marked.training_included]
            self.assertEqual(excluded[["route", "hour"]].values.tolist(), [[1, 1], [1, 2]])
            self.assertEqual(int(marked.boardings.sum()), 480)
            summary = training_mask_summary(frame, mask)
            self.assertEqual(summary["excluded_hours"], 2)
            self.assertEqual(summary["excluded_target_sum"], 20)
            self.assertEqual(summary["cleaned_target_sum"], 460)

    def test_mask_rejects_partial_hours_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_mask(Path(directory), start="2025-01-02 01:30:00")
            with self.assertRaisesRegex(ValueError, "partial hours require event-level"):
                load_training_mask(path)

    def test_mask_rejects_unverified_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_mask(Path(directory))
            document = json.loads(path.read_text())
            document["rules"][0]["verification_status"] = "candidate"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not verified"):
                load_training_mask(path)

    def test_masked_training_requires_explicit_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mask_path = write_mask(root)
            report_path = root / "comparison.json"
            report_path.write_text(
                json.dumps(
                    {
                        "selected_model": "calendar_holiday_hgbt",
                        "interval": {"absolute_error_q90": 1.0},
                        "training_mask": {
                            "mask_id": "synthetic-mask-v1",
                            "mask_sha256": load_training_mask(mask_path)["sha256"],
                        },
                        "adoption_decision": "requires Igor and Daniel review; no automatic adoption",
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                evaluation_report=str(report_path),
                training_mask=str(mask_path),
                dataset_dir="unused",
                artifact_dir="unused",
                weather_factors=None,
            )
            with self.assertRaisesRegex(ValueError, "adoption_decision='adopted'"):
                command_train(args)

    def test_masked_training_rejects_a_different_mask_than_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mask_path = write_mask(root)
            report_path = root / "comparison.json"
            report_path.write_text(
                json.dumps(
                    {
                        "selected_model": "calendar_holiday_hgbt",
                        "interval": {"absolute_error_q90": 1.0},
                        "training_mask": {
                            "mask_id": "synthetic-mask-v1",
                            "mask_sha256": "not-the-mask-checksum",
                        },
                        "adoption_decision": "adopted",
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                evaluation_report=str(report_path),
                training_mask=str(mask_path),
                dataset_dir="unused",
                artifact_dir="unused",
                weather_factors=None,
            )
            with patch("ml.cli.create_artifact") as create_artifact:
                with self.assertRaisesRegex(ValueError, "differs from the reviewed"):
                    command_train(args)
                create_artifact.assert_not_called()


class HistoryDropTests(unittest.TestCase):
    def test_drop_detection_does_not_impute_or_invent_a_cause(self):
        dates = pd.date_range("2025-01-01", periods=36, freq="D")
        frame = pd.DataFrame(
            {
                "route": 1,
                "date": dates,
                "hour": 0,
                "boardings": 100,
            }
        )
        frame.loc[frame.date.eq(pd.Timestamp("2025-02-05")), "boardings"] = 1
        result = history_drop_candidates(frame, routes=[1])
        candidate = result[result.date.eq(pd.Timestamp("2025-02-05"))].iloc[0]
        self.assertEqual(candidate.boardings, 1)
        self.assertEqual(candidate.cause_status, "unknown_unverified")
        self.assertFalse(candidate.recovery_applied)


if __name__ == "__main__":
    unittest.main()
