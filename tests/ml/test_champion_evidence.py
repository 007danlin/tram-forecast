"""Synthetic regression checks for the handoff CSV audit, no real data."""

import csv
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from scripts.champion_evidence import compare_csv


class ChampionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = [dict(route=str(route), date=(date(2025, 11, 1) + timedelta(days=day)).isoformat(),
                          hour=hour, prediction=0 if route == 5 else 100)
                     for route in (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)
                     for day in range(61) for hour in range(24)]
        self.write("base.csv", self.rows)

    def write(self, name, rows):
        with (self.root / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["route", "date", "hour", "prediction"], delimiter=";")
            writer.writeheader()
            writer.writerows(rows)

    def audit(self, rows):
        self.write("candidate.csv", rows)
        return compare_csv(self.root / "base.csv", self.root / "candidate.csv")

    def test_only_ordinary_weekends_allowed(self):
        candidate = [dict(r) for r in self.rows]
        for r in candidate:
            if r["route"] == "50" and r["date"] == "2025-11-02":
                r["prediction"] = 12
        result = self.audit(candidate)
        self.assertEqual(result["changed_rows"], 24)
        self.assertEqual(result["allowed_rows"], 408)
        self.assertFalse(result["platform_result"]["uploaded_bytes_independently_verified_by_this_script"])

    def test_working_saturday_and_holidays_rejected(self):
        for day in ("2025-11-01", "2025-11-03", "2025-11-04", "2025-12-31"):
            with self.subTest(day=day):
                candidate = [dict(r) for r in self.rows]
                next(r for r in candidate if r["route"] == "50" and r["date"] == day)["prediction"] = 12
                with self.assertRaises(ValueError):
                    self.audit(candidate)

    def test_other_route_change_rejected(self):
        candidate = [dict(r) for r in self.rows]
        candidate[0]["prediction"] = 12
        with self.assertRaises(ValueError):
            self.audit(candidate)

    def test_reordered_keys_rejected(self):
        with self.assertRaises(ValueError):
            self.audit(list(reversed(self.rows)))

    def test_nonzero_route5_rejected_even_if_both_files_agree(self):
        candidate = [dict(r) for r in self.rows]
        next(r for r in candidate if r["route"] == "5")["prediction"] = 1
        self.write("base.csv", candidate)
        with self.assertRaises(ValueError):
            self.audit(candidate)


if __name__ == "__main__":
    unittest.main()
