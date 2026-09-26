"""Preserved synthetic v1 and read-only HTTP access to validated ML batches."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from ml import adapter
from backend.handoff.api import HandoffError, error_handler, router
from backend.handoff.scenarios import router as scenario_router
from backend.handoff.store import load_snapshot
from backend.monitoring.api import router as monitoring_router
from backend.monitoring.service import Monitor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.handoff_snapshot = None
    directory = os.environ.get("TRAMFLOW_HANDOFF_DIR")
    if directory:
        try:
            app.state.handoff_snapshot = load_snapshot(Path(directory))
            logger.info(
                "ML batch loaded run=%s rows=%s",
                app.state.handoff_snapshot.run_id,
                len(app.state.handoff_snapshot.cells),
            )
        except Exception:
            logger.exception("ML handoff rejected; v2 unavailable")
    app.state.monitor = Monitor(
        os.environ.get("TRAMFLOW_MONITOR_DIR", "artifacts/monitoring/live"),
        enabled=os.environ.get("TRAMFLOW_MONITOR_ENABLED", "1") == "1",
        weather_provider=os.environ.get("TRAMFLOW_WEATHER_PROVIDER", "met"),
    )
    await app.state.monitor.start()
    try:
        yield
    finally:
        await app.state.monitor.close()
        app.state.handoff_snapshot = None


app = FastAPI(title="TramFlow API", version="0.2.0", lifespan=lifespan)
app.include_router(router)
app.include_router(scenario_router)
app.include_router(monitoring_router)
app.add_exception_handler(HandoffError, error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(("/api/v2/handoff/", "/api/v2/scenarios/")):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Invalid filters; see /docs for supported fields and limits",
                    "request_id": getattr(request.state, "request_id", None),
                    "fields": [list(e["loc"]) for e in exc.errors()],
                }
            },
        )
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def handoff_diagnostics(request: Request, call_next):
    if not request.url.path.startswith(("/api/v2/handoff/", "/api/v2/scenarios/")):
        return await call_next(request)
    request.state.request_id = str(uuid4())
    start = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Handoff request failed request_id=%s", request.state.request_id
        )
        response = await error_handler(
            request,
            HandoffError(
                503, "forecast_unavailable", "Forecast temporarily unavailable"
            ),
        )
    response.headers["X-Request-Id"] = request.state.request_id
    snapshot = getattr(request.app.state, "handoff_snapshot", None)
    logger.info(
        "request_id=%s endpoint=%s latency_ms=%.2f status=%s run=%s cache=disabled",
        request.state.request_id,
        request.url.path,
        (perf_counter() - start) * 1000,
        response.status_code,
        snapshot.run_id if snapshot else None,
    )
    return response


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Point(BaseModel):
    timestamp: AwareDatetime
    value: int = Field(ge=0, strict=True)


class Forecast(BaseModel):
    is_mock: Literal[True]
    unit: Literal["passengers"]
    points: list[Point] = Field(min_length=1)


@app.get("/api/v1/health", response_model=Health)
def health() -> Health:
    return Health()


@app.get("/api/v1/forecast", response_model=Forecast)
def get_forecast() -> Forecast:
    try:
        return Forecast.model_validate(adapter.predict_for_api_v1())
    except Exception as exc:
        logger.exception("ML mock failed")
        raise HTTPException(
            status_code=503, detail="Forecast temporarily unavailable"
        ) from exc
