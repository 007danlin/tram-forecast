"""Actual HTTP surface for supplied batches; not the unapproved general v2 draft."""

import csv
import hashlib
import io
import json
import logging
import math
from datetime import timedelta
from typing import Annotated, Literal, Self
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, model_validator

from backend.contracts.v2 import (
    ContractModel,
    Identifier,
    IsoDatetime,
    MOSCOW,
    Period,
    Value,
    validate_boundary,
)
from backend.handoff.store import Snapshot
from backend.handoff.features import SCENARIO, YEAR, ScenarioCapabilities, YearCapabilities

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/handoff", tags=["ML handoff v1"])
WARNINGS = [
    "Historical batch, not a live forecast for the current date.",
    "Organizer raw timezone is unconfirmed; calendar labels are interpreted as Europe/Moscow per ML metadata.",
    "Successful validations/boardings are not onboard occupancy.",
    "Route 5 uses an explicit zero baseline, not a trained route forecast.",
    "Values are unrounded; submission rounding is separate.",
]


class HandoffError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


class HandoffErrorBody(ContractModel):
    code: Literal[
        "unknown_route",
        "run_unavailable",
        "request_too_large",
        "artifacts_unavailable",
        "forecast_unavailable",
        "result_mismatch",
    ]
    message: str
    request_id: str


class HandoffErrorResponse(ContractModel):
    error: HandoffErrorBody


class HandoffValidationBody(ContractModel):
    code: Literal["invalid_request"]
    message: str
    request_id: str
    fields: list[list[str | int]]


class HandoffValidationResponse(ContractModel):
    error: HandoffValidationBody


ERROR_RESPONSES = {
    status: {"model": HandoffErrorResponse, "description": description}
    for status, description in (
        (404, "Route outside the delivered catalogue"),
        (410, "Requested run is not loaded"),
        (413, "Requested result exceeds the row limit"),
        (503, "No validated release or forecast temporarily unavailable"),
    )
}
QUERY_RESPONSES = {
    **ERROR_RESPONSES,
    422: {"model": HandoffValidationResponse, "description": "Invalid request fields"},
}


class HandoffReady(ContractModel):
    status: Literal["ready"]
    forecast_run_id: str
    source: Literal["validated_csv"]
    model_loaded: Literal[False]
    rows: int


class HandoffRoute(ContractModel):
    route_id: Identifier
    method: Literal["model", "baseline"]


class HandoffLimits(ContractModel):
    max_days: int
    max_rows: int
    retained_runs: int


class HandoffCapabilities(Period):
    schema_version: Literal["ml-handoff-v1"]
    forecast_run_id: str
    metric_id: Literal["successful_validations"]
    unit: Literal["successful_boardings"]
    timezone: Literal["Europe/Moscow"]
    routes: list[HandoffRoute]
    spatial_levels: list[Literal["route"]]
    directions_supported: Literal[False]
    resolutions: list[Literal["hour", "day"]]
    scenario_supported: Literal[True]
    scenario: ScenarioCapabilities
    year: YearCapabilities
    limits: HandoffLimits
    warnings: list[str]
    limitations: list[str]


class Query(Period):
    route_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    resolution: Literal["hour", "day"] = "hour"
    forecast_run_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        validate_boundary(self.start, self.resolution)
        validate_boundary(self.end, self.resolution)
        if self.end - self.start > timedelta(days=31):
            raise ValueError("Maximum request interval is 31 days")
        return self


class Export(Query):
    forecast_run_id: Identifier
    expected_result_id: Identifier


class Row(Period):
    route_id: Identifier
    value: Value | None
    reference_value: Value | None
    lower_90: Value | None
    upper_90: Value | None
    priority_score: Value | None
    status: Literal["ok", "cold_start_zero_baseline", "partial", "no_data"]
    method: Literal["model", "baseline"]
    expected_hours: int
    available_hours: int
    coverage: float


class Result(ContractModel):
    schema_version: Literal["ml-handoff-v1"] = "ml-handoff-v1"
    request_id: str
    result_id: str
    forecast_run_id: str
    model_version: str
    dataset_version: str
    csv_sha256: str
    imported_at: IsoDatetime
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    metric_id: Literal["successful_validations"] = "successful_validations"
    unit: Literal["successful_boardings"] = "successful_boardings"
    filters: Query
    interval_method: str
    warnings: list[str]
    limitations: list[str]
    rows: list[Row]
    total: Value | None
    total_scope: Literal["complete", "available_only", "no_data"]
    coverage: float


def get_snapshot(request: Request) -> Snapshot:
    snapshot = getattr(request.app.state, "handoff_snapshot", None)
    if snapshot is None:
        raise HandoffError(
            503, "artifacts_unavailable", "No validated ML release is loaded"
        )
    return snapshot


def calculate(snapshot: Snapshot, query: Query, request_id: str) -> Result:
    if query.forecast_run_id is not None and query.forecast_run_id != snapshot.run_id:
        raise HandoffError(
            410, "run_unavailable", "Requested run is not loaded; refresh capabilities"
        )
    if set(query.route_ids) - set(snapshot.routes):
        raise HandoffError(
            404, "unknown_route", "Route is outside the delivered model catalogue"
        )
    routes = sorted(set(query.route_ids), key=int)
    start, end = query.start.astimezone(MOSCOW), query.end.astimezone(MOSCOW)
    normalized = Query(
        start=start,
        end=end,
        resolution=query.resolution,
        route_ids=routes,
        forecast_run_id=snapshot.run_id,
    )
    key = {
        "calculation_version": "handoff-calc-1",
        **normalized.model_dump(mode="json"),
    }
    result_id = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    step = timedelta(hours=1) if query.resolution == "hour" else timedelta(days=1)
    if len(routes) * int((end - start) / step) > 10000:
        raise HandoffError(413, "request_too_large", "Reduce routes or interval")
    rows = []
    available_total = expected_total = 0
    for route in routes:
        stamp = start
        while stamp < end:
            stop = stamp + step
            expected = 1 if query.resolution == "hour" else 24
            cells = [
                snapshot.cells[(route, stamp + timedelta(hours=h))]
                for h in range(expected)
                if (route, stamp + timedelta(hours=h)) in snapshot.cells
            ]
            count = len(cells)
            expected_total += expected
            available_total += count
            status = (
                "cold_start_zero_baseline" if route in snapshot.cold_routes else "ok"
            )
            if count != expected:
                status = "partial" if count else "no_data"
            single = cells[0] if query.resolution == "hour" and cells else None
            rows.append(
                Row(
                    route_id=route,
                    start=stamp,
                    end=stop,
                    value=math.fsum(c.prediction for c in cells) if cells else None,
                    reference_value=math.fsum(c.reference for c in cells)
                    if cells and all(c.reference is not None for c in cells)
                    else None,
                    lower_90=single.lower if single else None,
                    upper_90=single.upper if single else None,
                    priority_score=single.priority_score if single else None,
                    status=status,
                    method="baseline" if route in snapshot.cold_routes else "model",
                    expected_hours=expected,
                    available_hours=count,
                    coverage=count / expected,
                )
            )
            stamp = stop
    warnings = list(WARNINGS)
    if available_total != expected_total:
        warnings.append(
            "Incomplete coverage: totals include available values only; missing values remain null."
        )
    if query.resolution == "day":
        warnings.append(
            "Daily bounds and priority are unavailable; hourly uncertainty bounds are not summed."
        )
    return Result(
        request_id=request_id,
        result_id=result_id,
        forecast_run_id=snapshot.run_id,
        model_version=snapshot.model_version,
        dataset_version=snapshot.dataset_version,
        csv_sha256=snapshot.csv_sha256,
        imported_at=snapshot.imported_at,
        filters=normalized,
        interval_method=snapshot.interval_method,
        warnings=warnings,
        limitations=list(snapshot.limitations),
        rows=rows,
        total=math.fsum(r.value for r in rows if r.value is not None)
        if available_total
        else None,
        total_scope="complete"
        if available_total == expected_total
        else ("available_only" if available_total else "no_data"),
        coverage=available_total / expected_total,
    )


@router.get(
    "/ready", response_model=HandoffReady, responses={503: ERROR_RESPONSES[503]}
)
def ready(request: Request):
    snapshot = get_snapshot(request)
    return {
        "status": "ready",
        "forecast_run_id": snapshot.run_id,
        "source": "validated_csv",
        "model_loaded": False,
        "rows": len(snapshot.cells),
    }


@router.get(
    "/capabilities",
    response_model=HandoffCapabilities,
    responses={503: ERROR_RESPONSES[503]},
)
def capabilities(request: Request):
    snapshot = get_snapshot(request)
    return {
        "schema_version": "ml-handoff-v1",
        "forecast_run_id": snapshot.run_id,
        "metric_id": "successful_validations",
        "unit": "successful_boardings",
        "timezone": "Europe/Moscow",
        "start": snapshot.start,
        "end": snapshot.end,
        "routes": [
            {
                "route_id": r,
                "method": "baseline" if r in snapshot.cold_routes else "model",
            }
            for r in snapshot.routes
        ],
        "spatial_levels": ["route"],
        "directions_supported": False,
        "resolutions": ["hour", "day"],
        "scenario_supported": True,
        "scenario": SCENARIO,
        "year": YEAR,
        "limits": {"max_days": 31, "max_rows": 10000, "retained_runs": 1},
        "warnings": WARNINGS,
        "limitations": snapshot.limitations,
    }


@router.post("/query", response_model=Result, responses=QUERY_RESPONSES)
def query(body: Query, request: Request):
    return calculate(get_snapshot(request), body, request.state.request_id)


@router.post(
    "/export",
    response_class=StreamingResponse,
    responses={
        **QUERY_RESPONSES,
        409: {
            "model": HandoffErrorResponse,
            "description": "Export does not match expected result",
        },
        200: {
            "content": {"text/csv": {"schema": {"type": "string"}}},
            "description": "Pinned unrounded result, not the organizer submission format",
            "headers": {
                "X-Result-Id": {"schema": {"type": "string"}},
                "Content-Disposition": {"schema": {"type": "string"}},
            },
        },
    },
)
def export(body: Export, request: Request):
    result = calculate(
        get_snapshot(request),
        Query.model_validate(body.model_dump(exclude={"expected_result_id"})),
        request.state.request_id,
    )
    if body.expected_result_id != result.result_id:
        raise HandoffError(
            409, "result_mismatch", "Export does not match the viewed result"
        )

    def stream():
        fields = [
            "route_id",
            "start",
            "end",
            "value",
            "reference_value",
            "lower_90",
            "upper_90",
            "priority_score",
            "status",
            "method",
            "expected_hours",
            "available_hours",
            "coverage",
        ]
        metadata = {
            "forecast_run_id": result.forecast_run_id,
            "result_id": result.result_id,
            "model_version": result.model_version,
            "dataset_version": result.dataset_version,
            "metric_id": result.metric_id,
            "unit": result.unit,
            "timezone": result.timezone,
        }
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields + list(metadata))
        yield "\ufeff"
        writer.writeheader()
        yield buffer.getvalue()
        for row in result.rows:
            buffer.seek(0)
            buffer.truncate()
            writer.writerow({**row.model_dump(mode="json"), **metadata})
            yield buffer.getvalue()

    return StreamingResponse(
        stream(),
        media_type="text/csv; charset=utf-8",
        headers={
            "X-Result-Id": result.result_id,
            "Content-Disposition": 'attachment; filename="tramflow-forecast.csv"',
        },
    )


async def error_handler(request: Request, exc: HandoffError):
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": getattr(request.state, "request_id", str(uuid4())),
            }
        },
    )
