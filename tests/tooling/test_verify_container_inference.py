"""Regression checks against false positive inference acceptance; no real data."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import verify_container_inference as verify


class InferenceVerificationTests(unittest.TestCase):
    def test_successful_computation_cannot_reuse_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "previous-call"
            existing.mkdir()
            (existing / "forecast.csv").write_text("must never be mounted for another calculation")
            runner = verify.DockerRunner(root, "unused-image", {})
            with patch.object(runner, "command") as command, self.assertRaises(FileExistsError):
                runner.infer("submission", root / "model", root / "sample.csv", output=existing)
            command.assert_not_called()

    def test_tiny_float_difference_is_not_hidden_by_tolerance_or_float_parser(self):
        row = {"route": "1", "date": "2025-11-01", "hour": "0", "prediction": "1", "status": "ok"}
        result = verify.compare_rows([dict(row, prediction="1.00000000000000001")], [row], ["prediction"])
        self.assertFalse(result["numeric_equal"])
        self.assertEqual(result["numeric"]["prediction"]["different"], 1)
        self.assertEqual(result["numeric"]["prediction"]["max_absolute_error"], "1E-17")

    def test_keys_order_status_and_nonfinite_are_checked(self):
        rows = [{"route": "1", "date": "2025-11-01", "hour": str(h), "prediction": "0", "status": "ok"} for h in (0, 1)]
        self.assertFalse(verify.compare_rows(rows[:1], rows, ["prediction"])["numeric_equal"])
        self.assertFalse(verify.compare_rows(rows[::-1], rows, ["prediction"])["order_equal"])
        self.assertFalse(verify.compare_rows([dict(rows[0], status="fallback"), rows[1]], rows, ["prediction"])["numeric_equal"])
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            verify.compare_rows([dict(rows[0], prediction="NaN")], rows, ["prediction"])

    def test_malformed_csv_and_duplicates_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "input.csv"
            p.write_text("route;date;hour;prediction\n1;2025-11-01;0;1\n1;2025-11-01;0;2\n")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                verify.read_csv(p, [*verify.KEYS, "prediction"])
            p.write_text("route;date;hour;prediction\n1;2025-11-01;0\n")
            with self.assertRaisesRegex(ValueError, "Malformed"):
                verify.read_csv(p, [*verify.KEYS, "prediction"])

    def test_failed_run_cannot_pass_comparison_and_report_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run").mkdir()
            (root / "run/report.json").write_text('{"passed": false, "stage": "run"}')
            argv = ["verify", "compare", "--run-dir", str(root / "run"), "--reference-forecast", "absent",
                    "--reference-submission", "absent", "--output-dir", str(root / "comparison")]
            with patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify.main(), 1)
                report = (root / "comparison/report.json").read_bytes()
                self.assertFalse(json.loads(report)["passed"])
                with self.assertRaises(FileExistsError):
                    verify.main()
                self.assertEqual((root / "comparison/report.json").read_bytes(), report)

    def test_corrupt_g0_is_rejected_before_inputs_are_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            g0 = root / "g0"
            g0.mkdir()
            (g0 / "model.joblib").write_bytes(b"synthetic corrupted artifact")
            (g0 / "bundle-manifest.json").write_text(json.dumps({"files": {"model.joblib": "0" * 64}}))
            argv = ["verify", "prepare", "--g0", str(g0), "--output-dir", str(root / "prepared")]
            with patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify.main(), 1)
            self.assertEqual({p.name for p in (root / "prepared").iterdir()}, {"report.json"})

    def test_run_parser_has_no_reference_arguments(self):
        with patch("sys.argv", ["verify", "run", "--help"]), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exit_:
                verify.main()
        self.assertEqual(exit_.exception.code, 0)
        self.assertNotIn("--reference", output.getvalue())


if __name__ == "__main__":
    unittest.main()
