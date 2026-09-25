"""Boundary cases for the draft wire contract; no model quality claims."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from backend.contracts.examples import build_examples
from backend.contracts.openapi import build_openapi
from backend.contracts.v2 import (
    Capabilities,
    ErrorResponse,
    ForecastExport,
    ForecastQuery,
    ForecastResponse,
    ForecastRow,
    Network,
    Quality,
    Ready,
    Scenario,
)
from backend.main import app


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.examples = build_examples()
        self.query = deepcopy(self.examples["query"])

    def test_all_review_examples_validate(self):
        ForecastQuery.model_validate(self.query)
        ForecastExport.model_validate(self.examples["export"])
        for name, response in self.examples["responses"].items():
            with self.subTest(name=name):
                ForecastResponse.model_validate_json(json.dumps(response))
        for error in self.examples["errors"].values():
            ErrorResponse.model_validate(error["body"])
        for key, model in (
            ("ready", Ready),
            ("not_ready", Ready),
            ("capabilities", Capabilities),
            ("network", Network),
            ("quality", Quality),
        ):
            model.model_validate(self.examples[key])

    def test_rejects_missing_timezone_epoch_and_unaligned_times(self):
        for start in (
            "2026-01-01T09:00:00",
            1767250800,
            "2026-01-01T09:01:00+03:00",
            "2026-01-01T09:00:00.001+03:00",
        ):
            with self.subTest(start=start), self.assertRaises(ValidationError):
                ForecastQuery.model_validate({**self.query, "start": start})

    def test_equivalent_utc_boundary_is_valid(self):
        query = ForecastQuery.model_validate(
            {**self.query, "start": "2026-01-01T06:00:00Z"}
        )
        self.assertEqual(query.start, ForecastQuery.model_validate(self.query).start)

    def test_rejects_empty_reversed_and_too_long_period(self):
        for end in (
            self.query["start"],
            "2026-01-01T08:00:00+03:00",
            "2026-01-02T10:00:00+03:00",
        ):
            with self.subTest(end=end), self.assertRaises(ValidationError):
                ForecastQuery.model_validate({**self.query, "end": end})

    def test_day_boundaries_use_moscow_not_input_offset(self):
        query = {
            **self.query,
            "horizon": "month",
            "resolution": "day",
            "start": "2025-12-31T21:00:00Z",
            "end": "2026-01-30T21:00:00Z",
        }
        ForecastQuery.model_validate(query)
        with self.assertRaises(ValidationError):
            ForecastQuery.model_validate({**query, "start": "2026-01-01T00:00:00Z"})

    def test_rejects_month_boundary_inside_month(self):
        query = {
            **self.query,
            "horizon": "year",
            "resolution": "month",
            "start": "2026-01-02T00:00:00+03:00",
            "end": "2027-01-01T00:00:00+03:00",
        }
        with self.assertRaises(ValidationError):
            ForecastQuery.model_validate(query)

    def test_identifiers_are_nonempty_strings_and_routes_bounded(self):
        for ids in ([], [1], [True], [""], ["two words"], ["r"] * 101):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                ForecastQuery.model_validate({**self.query, "route_ids": ids})

    def test_typos_do_not_silently_disable_filters(self):
        with self.assertRaises(ValidationError):
            ForecastQuery.model_validate({**self.query, "route_id": "another"})

    def test_coefficients_reject_nonfinite_boolean_strings_and_wrong_steps(self):
        for k in (-1, 0, 1.51, 1.03, float("nan"), float("inf"), True, "1.2"):
            with self.subTest(k=k), self.assertRaises(ValidationError):
                Scenario(k_weather=k)

    def test_coefficient_product_rejects_both_extremes_without_clipping(self):
        for k in (0.5, 1.5):
            with self.subTest(k=k), self.assertRaises(ValidationError):
                Scenario(k_weather=k, k_event=k, k_season=k)
        self.assertEqual(Scenario(k_weather=1.25, k_event=0.8).k_weather, 1.25)

    def test_export_requires_run_and_expected_result(self):
        for field in ("forecast_run_id", "expected_result_id"):
            request = deepcopy(self.examples["export"])
            request.pop(field)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ForecastExport.model_validate(request)

    def test_missing_forecast_cannot_be_zero_and_zero_can_be_available(self):
        row = self.examples["responses"]["success"]["rows"][2]
        ForecastRow.model_validate(row)
        with self.assertRaises(ValidationError):
            ForecastRow.model_validate({**row, "status": "no_data"})
        ForecastRow.model_validate(
            {**row, "status": "no_data", "value": None, "base_value": None}
        )

    def test_rejects_negative_nonfinite_and_coerced_forecast_values(self):
        row = self.examples["responses"]["success"]["rows"][0]
        for value in (-1, float("nan"), float("inf"), True, "12"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ForecastRow.model_validate({**row, "value": value})

    def test_qualitative_cannot_claim_numeric_forecast(self):
        row = self.examples["responses"]["qualitative"]["rows"][0]
        for change in ({"value": 1}, {"assumptions": []}, {"outlook": None}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ForecastRow.model_validate({**row, **change})

    def test_interval_needs_method_coverage_and_ordered_bounds(self):
        row = self.examples["responses"]["success"]["rows"][0]
        for change in (
            {"lower": 1},
            {
                "lower": 20,
                "upper": 5,
                "interval_method": "demo",
                "interval_coverage": 0.9,
            },
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ForecastRow.model_validate({**row, **change})

    def test_response_cannot_mix_runs_routes_or_coverage(self):
        for mutation in ("run", "route", "coverage", "end"):
            response = deepcopy(self.examples["responses"]["success"])
            if mutation == "run":
                response["forecast_run_id"] = "other"
            elif mutation == "route":
                response["rows"][0]["route_id"] = "other"
            elif mutation == "coverage":
                response["summary"]["coverage"] = 0.5
            else:
                response["rows"][-1]["end"] = "2026-01-01T14:00:00+03:00"
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                ForecastResponse.model_validate(response)

    def test_synthetic_readiness_cannot_claim_real_model(self):
        with self.assertRaises(ValidationError):
            Ready.model_validate({**self.examples["ready"], "real_ready": True})

    def test_synthetic_quality_cannot_claim_measurements(self):
        quality = {
            **self.examples["quality"],
            "metrics": [
                {"name": "wape_score", "value": 0.9, "description": "unmeasured"}
            ],
        }
        with self.assertRaises(ValidationError):
            Quality.model_validate(quality)

    def test_known_reference_examples_preserve_partial_and_scenario_semantics(self):
        responses = self.examples["responses"]
        self.assertEqual(responses["success"]["summary"]["total"], 60)
        self.assertEqual(responses["partial"]["summary"]["total"], 40)
        self.assertEqual(responses["partial"]["coverage"], 0.75)
        self.assertEqual(responses["scenario"]["summary"]["total"], 72)
        self.assertEqual(
            [r["base_value"] for r in responses["scenario"]["rows"]], [10, 20, 0, 30]
        )

    def test_committed_artifacts_are_generated_from_current_models(self):
        root = Path(__file__).resolve().parents[1] / "contracts" / "generated"
        self.assertEqual(
            json.loads((root / "openapi-v2-draft.json").read_text()), build_openapi()
        )
        self.assertEqual(
            json.loads((root / "examples-v2-draft.json").read_text()), self.examples
        )

    def test_openapi_is_offline_and_all_six_operations_are_documented(self):
        draft = build_openapi()
        self.assertEqual(len(draft["paths"]), 6)
        self.assertEqual(
            set(app.openapi()["paths"]), {"/api/v1/health", "/api/v1/forecast"}
        )
        export = draft["paths"]["/api/v2/forecast/export"]["post"]["responses"]
        self.assertEqual(set(export["200"]["content"]), {"text/csv"})
        for status in ("404", "409", "410", "413", "422", "503"):
            self.assertEqual(
                export[status]["content"]["application/json"]["schema"]["$ref"],
                "#/components/schemas/ErrorResponse",
            )


if __name__ == "__main__":
    unittest.main()
