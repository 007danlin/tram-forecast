"""Proposed v2 wire types. These do not define organizer or ML file formats."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

Identifier = Annotated[StrictStr, Field(min_length=1, pattern=r"^\S+$")]
Value = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Fraction = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Coefficient = Annotated[
    float, Field(strict=True, ge=0.5, le=1.5, multiple_of=0.05, allow_inf_nan=False)
]
Horizon = Literal["day", "month", "year"]
Resolution = Literal["hour", "day", "month"]
SpatialLevel = Literal["route", "stop", "segment"]
Mode = Literal["synthetic", "model", "baseline", "qualitative"]
MOSCOW = ZoneInfo("Europe/Moscow")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class Scenario(ContractModel):
    k_weather: Coefficient = 1.0
    k_event: Coefficient = 1.0
    k_season: Coefficient = 1.0

    @model_validator(mode="after")
    def validate_product(self) -> Self:
        product = (
            Decimal(str(self.k_weather))
            * Decimal(str(self.k_event))
            * Decimal(str(self.k_season))
        )
        if not Decimal("0.50") <= product <= Decimal("2.00"):
            raise ValueError(
                "Combined scenario coefficient must be between 0.50 and 2.00"
            )
        return self


class Period(ContractModel):
    start: AwareDatetime
    end: AwareDatetime

    @field_validator("start", "end", mode="before")
    @classmethod
    def reject_epoch(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError(
                "Use an ISO 8601 timestamp with timezone, not an epoch number"
            )
        return value

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start; intervals are [start, end)")
        return self


class ForecastQuery(Period):
    forecast_run_id: Identifier | None = None
    horizon: Horizon
    resolution: Resolution
    metric_id: Identifier
    spatial_level: SpatialLevel
    route_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    direction_id: Identifier | None = None
    entity_ids: list[Identifier] = Field(default_factory=list)
    scenario: Scenario | None = None

    @model_validator(mode="after")
    def validate_grid(self) -> Self:
        # Horizon limits are capabilities-dependent; query may select a subinterval.
        start, end = self.start.astimezone(MOSCOW), self.end.astimezone(MOSCOW)
        for boundary in (start, end):
            if boundary.minute or boundary.second or boundary.microsecond:
                raise ValueError(
                    "Boundaries must align to whole hours in Europe/Moscow"
                )
            if self.resolution in ("day", "month") and boundary.hour:
                raise ValueError("Day/month boundaries must align to Moscow midnight")
            if self.resolution == "month" and boundary.day != 1:
                raise ValueError("Month boundaries must align to the first day")
        if self.horizon == "day" and end - start > timedelta(days=1):
            raise ValueError("Day query cannot exceed 24 hours")
        if self.horizon == "month" and end - start > timedelta(days=30):
            raise ValueError("Month query cannot exceed 30 days")
        if self.horizon == "year":
            try:
                limit = start.replace(year=start.year + 1)
            except ValueError:
                limit = start.replace(year=start.year + 1, day=28)
            if end > limit:
                raise ValueError("Year query cannot exceed 12 calendar months")
        return self


class ForecastExport(ForecastQuery):
    forecast_run_id: Identifier
    # Proposed CR-04/05 resolution: reject export if the expected result changed.
    expected_result_id: Identifier


class WarningItem(ContractModel):
    code: Identifier
    message: Annotated[StrictStr, Field(min_length=1)]


class Factor(ContractModel):
    source_id: Identifier
    status: Literal["used", "unavailable", "not_used"]
    description: StrictStr


class ForecastRow(Period):
    route_id: Identifier
    direction_id: Identifier | None
    entity_id: Identifier
    base_value: Value | None
    value: Value | None
    actual_value: Value | None
    reference_value: Value | None
    lower: Value | None
    upper: Value | None
    status: Literal["ok", "no_data", "unsupported", "no_service"]
    method: Mode
    priority: Literal["normal", "attention"] | None
    outlook: StrictStr | None = None
    assumptions: list[StrictStr] = Field(default_factory=list)
    interval_method: Identifier | None = None
    interval_coverage: Fraction | None = None

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        if self.method == "qualitative":
            if self.value is not None or self.base_value is not None:
                raise ValueError("Qualitative rows cannot have numeric forecasts")
            if not self.outlook or not self.assumptions:
                raise ValueError("Qualitative rows need outlook and assumptions")
        elif self.status == "ok" and (self.value is None or self.base_value is None):
            raise ValueError("An available numeric forecast needs base_value and value")
        if self.status in ("no_data", "unsupported"):
            if self.value is not None or self.base_value is not None:
                raise ValueError("Missing/unsupported forecasts must remain null")
        if self.status == "no_service" and (self.value != 0 or self.base_value != 0):
            raise ValueError("Confirmed no_service requires explicit zero values")
        interval = (
            self.lower,
            self.upper,
            self.interval_method,
            self.interval_coverage,
        )
        if any(v is not None for v in interval):
            if any(v is None for v in interval):
                raise ValueError("Intervals require both bounds, method and coverage")
            if self.lower > self.upper or self.value is None:
                raise ValueError("Invalid prediction interval")
        return self


class Summary(ContractModel):
    total: Value | None
    total_scope: Literal["complete", "available_only", "not_applicable"]
    peak_interval: Period | None
    peak_value: Value | None
    problem_objects: Annotated[int, Field(strict=True, ge=0)]
    coverage: Fraction | None

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if (self.peak_interval is None) != (self.peak_value is None):
            raise ValueError("Peak interval and value must be provided together")
        if self.total_scope == "not_applicable" and self.total is not None:
            raise ValueError("Non-applicable totals must be null")
        if self.total_scope == "complete" and self.coverage != 1:
            raise ValueError("Complete total requires complete coverage")
        return self


class ForecastResponse(ContractModel):
    schema_version: Literal["2.0-draft.1"] = "2.0-draft.1"
    request_id: Identifier
    result_id: Identifier
    forecast_run_id: Identifier
    model_version: Identifier
    dataset_version: Identifier
    network_version: Identifier
    # Proposed explicit versions for reproducibility, pending CR-04.
    facts_version: Identifier
    calculation_version: Identifier
    generated_at: AwareDatetime
    as_of: AwareDatetime
    data_cutoff: AwareDatetime
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    mode: Mode
    metric_id: Identifier
    unit: Identifier
    filters: ForecastQuery
    scenario: Scenario | None
    coverage: Fraction | None
    warnings: list[WarningItem]
    factors: list[Factor]
    rows: Annotated[list[ForecastRow], Field(max_length=10000)]
    summary: Summary

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if self.filters.forecast_run_id != self.forecast_run_id:
            raise ValueError("Response filters must pin the response run")
        if (
            self.filters.metric_id != self.metric_id
            or self.filters.scenario != self.scenario
        ):
            raise ValueError("Response metric/scenario must match its filters")
        if self.summary.coverage != self.coverage:
            raise ValueError("Summary and response coverage must agree")
        if self.data_cutoff > self.as_of or self.as_of > self.generated_at:
            raise ValueError("Expected data_cutoff <= as_of <= generated_at")
        if not self.rows and (
            self.coverage is not None or self.summary.total is not None
        ):
            raise ValueError("Empty results have null coverage and total")
        for row in self.rows:
            if row.start < self.filters.start or row.end > self.filters.end:
                raise ValueError("Row falls outside query interval")
            if row.route_id not in self.filters.route_ids:
                raise ValueError("Row falls outside requested routes")
            if (
                self.filters.direction_id is not None
                and row.direction_id != self.filters.direction_id
            ):
                raise ValueError("Row falls outside requested direction")
            if self.filters.entity_ids and row.entity_id not in self.filters.entity_ids:
                raise ValueError("Row falls outside requested entities")
            if self.scenario is not None and row.lower is not None:
                raise ValueError(
                    "Base calibrated intervals cannot be reused for manual scenarios"
                )
        return self


ErrorCode = Literal[
    "invalid_request",
    "unsupported_query",
    "unknown_id",
    "run_expired",
    "request_too_large",
    "artifacts_unavailable",
    "result_mismatch",
]


class ErrorBody(ContractModel):
    code: ErrorCode
    message: Annotated[StrictStr, Field(min_length=1)]
    request_id: Identifier
    details: list[WarningItem] = Field(default_factory=list)


class ErrorResponse(ContractModel):
    error: ErrorBody


ERROR_STATUS = {
    "invalid_request": 422,
    "unsupported_query": 422,
    "unknown_id": 404,
    "run_expired": 410,
    "request_too_large": 413,
    "artifacts_unavailable": 503,
    "result_mismatch": 409,
}


class Limits(ContractModel):
    max_routes: Annotated[int, Field(strict=True, ge=1, le=100)] = 100
    max_query_rows: Annotated[int, Field(strict=True, ge=1, le=10000)] = 10000
    max_export_rows: Annotated[int, Field(strict=True, ge=1, le=100000)] = 100000
    retention_seconds: Annotated[int, Field(strict=True, ge=0)]


class SupportedQuery(Period):
    metric_id: Identifier
    unit: Identifier
    additive: bool
    horizon: Horizon
    resolution: Resolution
    spatial_level: SpatialLevel
    mode: Mode
    direction_policy: Literal["required", "merge_allowed", "unavailable"]


class ScenarioRules(ContractModel):
    minimum: Literal[0.5] = 0.5
    maximum: Literal[1.5] = 1.5
    step: Literal[0.05] = 0.05
    neutral: Literal[1.0] = 1.0
    product_minimum: Literal[0.5] = 0.5
    product_maximum: Literal[2.0] = 2.0


class Capabilities(ContractModel):
    schema_version: Literal["2.0-draft.1"] = "2.0-draft.1"
    forecast_run_id: Identifier | None
    network_version: Identifier | None
    supported_queries: list[SupportedQuery]
    limits: Limits
    scenario_supported: bool
    scenario_rules: ScenarioRules | None
    factors: list[Factor]
    warnings: list[WarningItem]


class Ready(ContractModel):
    status: Literal["ready", "not_ready"]
    mode: Mode | None
    real_ready: bool
    forecast_run_id: Identifier | None
    checks: list[WarningItem]

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if self.status == "ready" and (
            self.forecast_run_id is None or self.mode is None
        ):
            raise ValueError("Ready requires a pinned run and mode")
        if self.real_ready and (
            self.status != "ready" or self.mode in (None, "synthetic")
        ):
            raise ValueError("Synthetic/unavailable artifacts cannot be real_ready")
        return self


Longitude = Annotated[float, Field(strict=True, ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]
Position = tuple[Longitude, Latitude]


class PointGeometry(ContractModel):
    type: Literal["Point"]
    coordinates: Position


class LineGeometry(ContractModel):
    type: Literal["LineString"]
    coordinates: Annotated[list[Position], Field(min_length=2)]


class MultiLineGeometry(ContractModel):
    type: Literal["MultiLineString"]
    coordinates: Annotated[
        list[Annotated[list[Position], Field(min_length=2)]], Field(min_length=1)
    ]


class NetworkProperties(ContractModel):
    spatial_level: SpatialLevel
    route_id: Identifier
    direction_id: Identifier | None
    entity_id: Identifier
    name: StrictStr
    sequence: Annotated[int, Field(strict=True, ge=0)] | None


class NetworkFeature(ContractModel):
    type: Literal["Feature"] = "Feature"
    properties: NetworkProperties
    geometry: (
        Annotated[
            PointGeometry | LineGeometry | MultiLineGeometry,
            Field(discriminator="type"),
        ]
        | None
    )


class Network(ContractModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    network_version: Identifier
    features: list[NetworkFeature]
    warnings: list[WarningItem]


class QualityMetric(ContractModel):
    name: Identifier
    value: Value
    description: StrictStr


class Quality(ContractModel):
    forecast_run_id: Identifier
    model_version: Identifier
    dataset_version: Identifier
    status: Literal["available", "not_evaluated"]
    metrics: list[QualityMetric]
    evaluation_period: Period | None
    methodology: StrictStr
    limitations: list[StrictStr]
    factors: list[Factor]

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.status == "not_evaluated" and self.metrics:
            raise ValueError("An unevaluated model must not claim measured metrics")
        if self.status == "available" and (
            not self.metrics or self.evaluation_period is None
        ):
            raise ValueError(
                "Measured quality requires metrics and an evaluation period"
            )
        return self
