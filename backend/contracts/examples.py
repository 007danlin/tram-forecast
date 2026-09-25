"""Explicitly synthetic review examples, never returned by the live API."""

from copy import deepcopy

from backend.contracts.v2 import ERROR_STATUS


def build_examples() -> dict:
    query = {
        "start": "2026-01-01T09:00:00+03:00",
        "end": "2026-01-01T13:00:00+03:00",
        "horizon": "day",
        "resolution": "hour",
        "metric_id": "synthetic_count",
        "spatial_level": "route",
        "route_ids": ["demo-route"],
        "direction_id": "demo-outbound",
        "entity_ids": [],
        "scenario": None,
    }
    filters = {**query, "forecast_run_id": "demo-run-1"}
    rows = []
    for hour, value in zip(range(9, 13), (10, 20, 0, 30)):
        rows.append(
            {
                "route_id": "demo-route",
                "direction_id": "demo-outbound",
                "entity_id": "demo-route",
                "start": f"2026-01-01T{hour:02d}:00:00+03:00",
                "end": f"2026-01-01T{hour + 1:02d}:00:00+03:00",
                "base_value": value,
                "value": value,
                "actual_value": None,
                "reference_value": None,
                "lower": None,
                "upper": None,
                "status": "ok",
                "method": "synthetic",
                "priority": None,
            }
        )
    success = {
        "schema_version": "2.0-draft.1",
        "request_id": "demo-request-success",
        "result_id": "example-only-success",
        "forecast_run_id": "demo-run-1",
        "model_version": "demo-model",
        "dataset_version": "demo-data",
        "network_version": "demo-network",
        "facts_version": "demo-facts",
        "calculation_version": "draft-calculation-1",
        "generated_at": "2026-01-01T08:00:00+03:00",
        "as_of": "2026-01-01T07:00:00+03:00",
        "data_cutoff": "2026-01-01T06:00:00+03:00",
        "timezone": "Europe/Moscow",
        "mode": "synthetic",
        "metric_id": "synthetic_count",
        "unit": "synthetic_units",
        "filters": filters,
        "scenario": None,
        "coverage": 1.0,
        "warnings": [
            {"code": "synthetic_example", "message": "Synthetic review fixture"}
        ],
        "factors": [],
        "rows": rows,
        "summary": {
            "total": 60,
            "total_scope": "complete",
            "peak_interval": {"start": rows[-1]["start"], "end": rows[-1]["end"]},
            "peak_value": 30,
            "problem_objects": 0,
            "coverage": 1.0,
        },
    }
    responses = {"success": success}
    for name in ("empty", "partial", "stale", "scenario", "qualitative"):
        responses[name] = deepcopy(success)
        responses[name]["request_id"] = f"demo-request-{name}"
        responses[name]["result_id"] = f"example-only-{name}"
    empty = responses["empty"]
    empty.update(rows=[], coverage=None)
    empty["summary"].update(
        total=None,
        total_scope="not_applicable",
        peak_interval=None,
        peak_value=None,
        coverage=None,
    )
    empty["warnings"].append(
        {"code": "empty_selection", "message": "No matching cells"}
    )
    partial = responses["partial"]
    partial["rows"][1].update(base_value=None, value=None, status="no_data")
    partial["coverage"] = 0.75
    partial["summary"].update(
        total=40, total_scope="available_only", coverage=0.75, problem_objects=1
    )
    partial["warnings"].append(
        {"code": "partial_coverage", "message": "Only available values summed"}
    )
    responses["stale"]["warnings"].append(
        {"code": "stale_run", "message": "Pinned run is stale"}
    )
    scenario = responses["scenario"]
    scenario["scenario"] = {"k_weather": 1.2, "k_event": 1.0, "k_season": 1.0}
    scenario["filters"]["scenario"] = deepcopy(scenario["scenario"])
    for row, value in zip(scenario["rows"], (12, 24, 0, 36)):
        row["value"] = value
    scenario["summary"].update(total=72, peak_value=36)
    qualitative = responses["qualitative"]
    qualitative["mode"] = "qualitative"
    qualitative["coverage"] = 0.0
    qualitative["filters"].update(
        start="2026-01-01T00:00:00+03:00",
        end="2027-01-01T00:00:00+03:00",
        horizon="year",
        resolution="month",
    )
    row = deepcopy(rows[0])
    row.update(
        start="2026-01-01T00:00:00+03:00",
        end="2026-02-01T00:00:00+03:00",
        base_value=None,
        value=None,
        method="qualitative",
        status="unsupported",
        outlook="Illustrative outlook only, not a numeric prediction",
        assumptions=["Synthetic review example; history is unavailable"],
    )
    qualitative["rows"] = []
    for month in range(1, 13):
        cell = deepcopy(row)
        cell["start"] = f"2026-{month:02d}-01T00:00:00+03:00"
        cell["end"] = (
            f"2026-{month + 1:02d}-01T00:00:00+03:00"
            if month < 12
            else "2027-01-01T00:00:00+03:00"
        )
        qualitative["rows"].append(cell)
    qualitative["summary"].update(
        total=None,
        total_scope="not_applicable",
        peak_interval=None,
        peak_value=None,
        coverage=0.0,
    )
    return {
        "notice": "Synthetic draft fixtures, not organizer data. result_id values are illustrative, not hashes.",
        "query": query,
        "export": {**filters, "expected_result_id": success["result_id"]},
        "responses": responses,
        "errors": {
            code: {
                "status": status,
                "body": {
                    "error": {
                        "code": code,
                        "message": code.replace("_", " "),
                        "request_id": f"demo-error-{code}",
                        "details": [],
                    }
                },
            }
            for code, status in ERROR_STATUS.items()
        },
        "ready": {
            "status": "ready",
            "mode": "synthetic",
            "real_ready": False,
            "forecast_run_id": "demo-run-1",
            "checks": [],
        },
        "not_ready": {
            "status": "not_ready",
            "mode": None,
            "real_ready": False,
            "forecast_run_id": None,
            "checks": [{"code": "missing_run", "message": "No validated run"}],
        },
        "capabilities": {
            "forecast_run_id": "demo-run-1",
            "network_version": "demo-network",
            "supported_queries": [
                {
                    "start": query["start"],
                    "end": query["end"],
                    "metric_id": "synthetic_count",
                    "unit": "synthetic_units",
                    "additive": True,
                    "horizon": "day",
                    "resolution": "hour",
                    "spatial_level": "route",
                    "mode": "synthetic",
                    "direction_policy": "required",
                }
            ],
            "limits": {"retention_seconds": 0},
            "scenario_supported": True,
            "scenario_rules": {
                "minimum": 0.5,
                "maximum": 1.5,
                "step": 0.05,
                "neutral": 1.0,
                "product_minimum": 0.5,
                "product_maximum": 2.0,
            },
            "factors": [],
            "warnings": success["warnings"],
        },
        "network": {
            "network_version": "demo-network",
            "features": [],
            "warnings": [
                {"code": "geometry_unavailable", "message": "No verified geometry"}
            ],
        },
        "quality": {
            "forecast_run_id": "demo-run-1",
            "model_version": "demo-model",
            "dataset_version": "demo-data",
            "status": "not_evaluated",
            "metrics": [],
            "evaluation_period": None,
            "methodology": "Synthetic contract fixture; no evaluation performed",
            "limitations": ["Not a trained model"],
            "factors": [],
        },
    }
