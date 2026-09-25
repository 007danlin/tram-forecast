"""Generate a review artifact without serving or modifying the production API."""

import argparse
import json
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Query, Response

from backend.contracts.examples import build_examples
from backend.contracts.v2 import (
    Capabilities,
    ErrorResponse,
    ForecastExport,
    ForecastQuery,
    ForecastResponse,
    Identifier,
    Network,
    Quality,
    Ready,
)


def build_openapi() -> dict:
    draft = FastAPI(
        title="TramFlow v2 — REVIEW ONLY",
        version="2.0-draft.1",
        description="Unapproved proposal. These routes are not in backend.main:app.",
    )
    examples = build_examples()
    errors = {
        status: {"model": ErrorResponse, "description": description}
        for status, description in (
            (404, "Unknown identifier"),
            (410, "Pinned version expired"),
            (413, "Request exceeds limits"),
            (422, "Invalid or unsupported query"),
            (503, "Artifacts unavailable"),
        )
    }

    def unimplemented():
        raise RuntimeError("Review-only route declaration; no v2 service implemented")

    @draft.post(
        "/api/v2/forecast/query",
        response_model=ForecastResponse,
        responses={
            **errors,
            200: {
                "content": {
                    "application/json": {
                        "examples": {
                            name: {"value": value}
                            for name, value in examples["responses"].items()
                        }
                    }
                }
            },
        },
    )
    def query(request: ForecastQuery):
        unimplemented()

    @draft.post(
        "/api/v2/forecast/export",
        response_class=Response,
        responses={
            **errors,
            409: {
                "model": ErrorResponse,
                "description": "Expected result does not match",
            },
            200: {
                "description": "UTF-8 CSV with BOM; same pinned result as query",
                "content": {"text/csv": {"schema": {"type": "string"}}},
                "headers": {
                    "X-Result-Id": {"schema": {"type": "string"}},
                    "Content-Disposition": {"schema": {"type": "string"}},
                },
            },
        },
    )
    def export(request: ForecastExport):
        unimplemented()

    @draft.get("/api/v2/capabilities", response_model=Capabilities, responses=errors)
    def capabilities():
        unimplemented()

    @draft.get(
        "/api/v2/network",
        response_model=Network,
        responses={
            **errors,
            200: {"headers": {"ETag": {"schema": {"type": "string"}}}},
            304: {"description": "Unchanged network for If-None-Match"},
        },
    )
    def network(
        network_version: Identifier,
        route_ids: Annotated[list[Identifier] | None, Query()] = None,
        if_none_match: Annotated[str | None, Header()] = None,
    ):
        unimplemented()

    @draft.get("/api/v2/quality", response_model=Quality, responses=errors)
    def quality(forecast_run_id: Identifier):
        unimplemented()

    @draft.get(
        "/api/v2/ready",
        response_model=Ready,
        responses={
            503: {
                "model": Ready,
                "description": "No compatible run; readiness check report",
            },
        },
    )
    def ready():
        unimplemented()

    schema = draft.openapi()
    schema["x-contract-status"] = "proposal-awaiting-owner-approval"
    schema["x-unresolved-decisions"] = [f"CR-{i:02d}" for i in range(1, 9)]
    schema["paths"]["/api/v2/forecast/query"]["post"]["requestBody"]["content"][
        "application/json"
    ]["example"] = examples["query"]
    schema["paths"]["/api/v2/forecast/export"]["post"]["requestBody"]["content"][
        "application/json"
    ]["example"] = examples["export"]
    return schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("backend/contracts/generated")
    )
    parser.add_argument(
        "--check", action="store_true", help="Check committed artifacts without writing"
    )
    args = parser.parse_args()
    artifacts = {
        "openapi-v2-draft.json": build_openapi(),
        "examples-v2-draft.json": build_examples(),
    }
    for name, value in artifacts.items():
        path = args.output / name
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if not path.is_file() or path.read_text() != text:
                raise SystemExit(f"Outdated contract artifact: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)


if __name__ == "__main__":
    main()
