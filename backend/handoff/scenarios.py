"""Explicit dispatcher assumptions over the immutable base, never ML inference."""
import csv
import hashlib
import io
import json
import math
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from backend.contracts.v2 import ContractModel, Identifier
from backend.handoff.api import (HandoffError, HandoffErrorResponse, QUERY_RESPONSES,
                                 Query, Result, Row, calculate, get_snapshot)
from backend.handoff.store import Snapshot

router = APIRouter(prefix="/api/v2/scenarios", tags=["Manual scenarios v1"])
VERSION = "manual-multiply-v1"
Coefficient = Annotated[float, Field(strict=True, ge=0.5, le=1.5, multiple_of=0.05, allow_inf_nan=False)]


class Coefficients(ContractModel):
    weather: Coefficient = 1.0
    event: Coefficient = 1.0
    closures: Coefficient = 1.0
    changes: Coefficient = 1.0


class ScenarioQuery(Query):
    coefficients: Coefficients


class ScenarioExport(ScenarioQuery):
    forecast_run_id: Identifier
    expected_result_id: Identifier


class ScenarioRow(Row):
    base_value: float | None
    delta: float | None


class ScenarioResult(ContractModel):
    schema_version: Literal["manual-scenario-v1"] = "manual-scenario-v1"
    calculation_version: Literal["manual-multiply-v1"] = VERSION
    result_id: str
    base: Result
    coefficients: Coefficients
    rows: list[ScenarioRow]
    total: float | None
    delta_total: float | None
    interval_method: Literal["not_estimated"] = "not_estimated"
    source: Literal["dispatcher_assumption"] = "dispatcher_assumption"


def calculate_scenario(snapshot: Snapshot, body: ScenarioQuery, request_id: str) -> ScenarioResult:
    base = calculate(snapshot, Query.model_validate(body.model_dump(exclude={"coefficients"})), request_id)
    key = {"calculation_version": VERSION, "base_result_id": base.result_id,
           "coefficients": {k: v for k, v in body.coefficients.model_dump().items()
                            if k in ("weather", "event") or v != 1.0}}
    result_id = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    rows = []
    for row in base.rows:
        value = None if row.value is None else row.value * body.coefficients.weather * body.coefficients.event * body.coefficients.closures * body.coefficients.changes
        rows.append(ScenarioRow(**{**row.model_dump(), "value": value,
            "base_value": row.value, "delta": None if value is None else value - row.value,
            "lower_90": None, "upper_90": None, "priority_score": None}))
    total = math.fsum(row.value for row in rows if row.value is not None) if base.total is not None else None
    return ScenarioResult(result_id=result_id, base=base, coefficients=body.coefficients,
        rows=rows, total=total, delta_total=None if total is None else total - base.total)


@router.post("/query", response_model=ScenarioResult, responses=QUERY_RESPONSES)
def query(body: ScenarioQuery, request: Request):
    return calculate_scenario(get_snapshot(request), body, request.state.request_id)


@router.post("/export", response_class=StreamingResponse, responses={
    **QUERY_RESPONSES,
    409: {"model": HandoffErrorResponse, "description": "Export does not match the viewed scenario"},
    200: {"content": {"text/csv": {"schema": {"type": "string"}}},
          "description": "Pinned manual scenario with base values and coefficients",
          "headers": {"X-Result-Id": {"schema": {"type": "string"}},
                      "Content-Disposition": {"schema": {"type": "string"}}}},
})
def export(body: ScenarioExport, request: Request):
    result = calculate_scenario(get_snapshot(request), ScenarioQuery.model_validate(
        body.model_dump(exclude={"expected_result_id"})), request.state.request_id)
    if body.expected_result_id != result.result_id:
        raise HandoffError(409, "result_mismatch", "Export does not match the viewed scenario")
    metadata = {"weather": result.coefficients.weather, "event": result.coefficients.event,
        "base_result_id": result.base.result_id, "result_id": result.result_id,
        "forecast_run_id": result.base.forecast_run_id, "model_version": result.base.model_version,
        "dataset_version": result.base.dataset_version, "unit": result.base.unit,
        "metric_id": result.base.metric_id, "timezone": result.base.timezone,
        "calculation_version": VERSION, "interval_method": result.interval_method,
        "source": result.source}

    # Keep legacy CSV columns unchanged for two-factor clients.
    for name in ("closures", "changes"):
        if name in body.coefficients.model_fields_set:
            metadata[name] = getattr(result.coefficients, name)

    def stream():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(ScenarioRow.model_fields) + list(metadata))
        yield "\ufeff"
        writer.writeheader()
        yield buffer.getvalue()
        for row in result.rows:
            buffer.seek(0)
            buffer.truncate()
            writer.writerow({**row.model_dump(mode="json"), **metadata})
            yield buffer.getvalue()

    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8", headers={
        "X-Result-Id": result.result_id,
        "Content-Disposition": 'attachment; filename="tramflow-manual-scenario.csv"'})
