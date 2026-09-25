import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.factors import (
    WEATHER_MODEL_COLUMNS,
    load_weather_factors,
    normalize_open_meteo_snapshot,
    official_calendar_2025,
)


class CalendarFactorTests(unittest.TestCase):
    def test_verified_2025_transfers_are_explicit(self):
        calendar = official_calendar_2025().set_index("date")
        self.assertEqual(calendar.loc[pd.Timestamp("2025-11-01"), "is_working_weekend"], 1)
        self.assertEqual(calendar.loc[pd.Timestamp("2025-11-01"), "is_day_off"], 0)
        self.assertEqual(calendar.loc[pd.Timestamp("2025-11-03"), "is_transferred_day_off"], 1)
        self.assertEqual(calendar.loc[pd.Timestamp("2025-11-03"), "is_day_off"], 1)
        self.assertEqual(calendar.loc[pd.Timestamp("2025-11-04"), "is_public_holiday"], 1)
        self.assertEqual(calendar.loc[pd.Timestamp("2025-12-31"), "is_transferred_day_off"], 1)


class WeatherFactorTests(unittest.TestCase):
    @staticmethod
    def _payload(*, missing_temperature=False):
        values = {
            "time": ["2025-01-01T00:00", "2025-01-01T01:00", "2025-01-01T02:00"],
            "temperature_2m": [-1.0, None if missing_temperature else 0.5, 2.0],
            "apparent_temperature": [-2.0, -0.5, 1.0],
            "precipitation": [0.0, 1.0, 2.0],
            "snowfall": [0.0, 0.4, 0.0],
            "snow_depth": [None, None, None],
            "wind_speed_10m": [2.0, 3.0, 4.0],
            "wind_gusts_10m": [5.0, 6.0, 7.0],
        }
        return {
            "latitude": 55.75,
            "longitude": 37.62,
            "timezone": "Europe/Moscow",
            "utc_offset_seconds": 10_800,
            "hourly_units": {},
            "hourly": values,
        }

    def test_normalization_preserves_source_and_excludes_unavailable_optional_field(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.json"
            normalized = root / "normalized.csv"
            manifest = root / "manifest.json"
            raw.write_text(json.dumps(self._payload()), encoding="utf-8")

            normalize_open_meteo_snapshot(raw, normalized, manifest, source_url="https://example.test")
            loaded = load_weather_factors(normalized)
            metadata = json.loads(manifest.read_text(encoding="utf-8"))

            self.assertEqual(len(loaded), 3)
            self.assertTrue(set(WEATHER_MODEL_COLUMNS).issubset(loaded.columns))
            self.assertNotIn("snow_depth", loaded.columns)
            self.assertIn("snow_depth", metadata["excluded_optional_columns"])
            self.assertEqual(metadata["information_mode"], "competition_retro")
            self.assertFalse(loaded[list(WEATHER_MODEL_COLUMNS)].isna().any().any())

    def test_required_weather_null_is_rejected_instead_of_imputed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.json"
            raw.write_text(json.dumps(self._payload(missing_temperature=True)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Required weather fields contain nulls"):
                normalize_open_meteo_snapshot(
                    raw,
                    root / "normalized.csv",
                    root / "manifest.json",
                    source_url="https://example.test",
                )


class FactorRegistryTests(unittest.TestCase):
    def test_all_16_factor_groups_have_owner_status_and_availability_decision(self):
        registry_path = Path(__file__).parents[2] / "ml" / "external-sources.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        factors = registry["factors"]
        self.assertEqual([factor["factor_id"] for factor in factors], [f"F{number:02d}" for number in range(1, 17)])
        for factor in factors:
            self.assertTrue(factor["owner_acquisition"])
            self.assertTrue(factor["owner_model_effect"])
            self.assertIn(factor["status"], registry["status_definitions"])
            self.assertIn(factor["decision"], {"included_in_selected_model", "excluded_no_incremental_selection_gain", "not_integrated"})
            self.assertTrue(factor["sources"] or factor["blocker"])


if __name__ == "__main__":
    unittest.main()
