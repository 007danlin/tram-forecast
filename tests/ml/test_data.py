import tempfile
import unittest
from pathlib import Path

from ml.data import build_target_from_raw


HEADER = "tran_date_time;validation_result;ngpt_route\n"


class DataTests(unittest.TestCase):
    def test_raw_builder_filters_by_calendar_time_and_success(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.csv"
            raw.write_text(
                HEADER
                + "2025-09-01 00:10:00;1;7 трамвай\n"
                + "2025-09-01 00:20:00;90;7 трамвай\n"
                + "2025-09-01 00:30:00;1;7 трамвай\n"
                + "2025-11-01 00:00:00;1;7 трамвай\n",
                encoding="utf-8",
            )
            result = build_target_from_raw([raw], "2025-09-01", "2025-10-31", chunksize=2)
            cell = result[(result.route == 7) & (result.date.astype(str) == "2025-09-01") & (result.hour == 0)]
            self.assertEqual(cell.boardings.item(), 2)
            self.assertEqual(int(result.boardings.sum()), 2)
            self.assertEqual(len(result), 10 * 61 * 24)


if __name__ == "__main__":
    unittest.main()
