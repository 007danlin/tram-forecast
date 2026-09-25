"""Minimal API connected directly to the in-process ML mock."""
import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from ml import adapter

app = FastAPI(title="TramFlow integration scaffold", version="0.1.0")
logger = logging.getLogger(__name__)


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
        raise HTTPException(status_code=503, detail="Forecast temporarily unavailable") from exc
