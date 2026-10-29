from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import services

app = FastAPI(
    title="Global Suicide Rates: Historical Analytics Dashboard API",
    version="1.0.0",
    description="Descriptive API for the 1950-2005 country-level dataset. No causal or predictive claims.",
)

origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def year_bounds(from_year: int, to_year: int) -> tuple[int, int]:
    if from_year > to_year:
        raise HTTPException(status_code=422, detail={"error": "invalid_year_range", "message": "'from' must be <= 'to'."})
    return from_year, to_year


def list_range(from_year: int, to_year: int) -> tuple[int, int]:
    start, end = year_bounds(from_year, to_year)
    return max(1950, start), min(2005, end)


@app.exception_handler(FileNotFoundError)
async def missing_data_handler(_, exc: FileNotFoundError):
    return JSONResponse(
        status_code=503, content={"error": "data_unavailable", "message": str(exc)}
    )


@app.exception_handler(KeyError)
async def unknown_entity_handler(_, exc: KeyError):
    return JSONResponse(
        status_code=404, content={"error": "entity_not_found", "message": f"Unknown entity: {exc.args[0]}"}
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": detail.get("error", "http_error"),
            "message": detail.get("message", str(exc.detail)),
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(_, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": "Request validation failed.", "details": details},
    )


@app.get("/api/v1/kpis")
def kpis(
    from_year: int = Query(1950, alias="from", ge=1950, le=2005),
    to_year: int = Query(2005, alias="to", ge=1950, le=2005),
):
    start, end = list_range(from_year, to_year)
    return services.get_kpis(start, end)


@app.get("/api/v1/trend/global")
def global_trend(
    from_year: int = Query(1950, alias="from", ge=1950, le=2005),
    to_year: int = Query(2005, alias="to", ge=1950, le=2005),
):
    start, end = list_range(from_year, to_year)
    return services.get_global_trend(start, end)


@app.get("/api/v1/countries/top")
def top_countries(
    n: int = Query(10, ge=1, le=100),
    from_year: int = Query(1950, alias="from", ge=1950, le=2005),
    to_year: int = Query(2005, alias="to", ge=1950, le=2005),
):
    start, end = list_range(from_year, to_year)
    return services.get_top_countries(n, start, end)


@app.get("/api/v1/countries")
def countries():
    return services.get_countries()


@app.get("/api/v1/compare")
def compare(
    entity: str = Query(..., min_length=1, max_length=100),
    from_year: int = Query(1950, alias="from", ge=1950, le=2005),
    to_year: int = Query(2005, alias="to", ge=1950, le=2005),
):
    start, end = list_range(from_year, to_year)
    return services.get_compare(entity, start, end)


@app.get("/api/v1/anomalies")
def anomalies(
    entity: str | None = Query(None, min_length=1, max_length=100),
    method: str = Query("zscore", pattern="^(zscore|iqr)$"),
    threshold: float = Query(2.0, gt=0, le=10),
    from_year: int = Query(1950, alias="from", ge=1950, le=2005),
    to_year: int = Query(2005, alias="to", ge=1950, le=2005),
):
    start, end = list_range(from_year, to_year)
    return [
        row
        for row in services.get_anomalies(entity, method, threshold)
        if start <= row["year"] <= end
    ]


@app.get("/api/v1/coverage")
def coverage(
    from_year: int = Query(1950, alias="from", ge=1950, le=2005),
    to_year: int = Query(2005, alias="to", ge=1950, le=2005),
    limit: int = Query(250, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    start, end = list_range(from_year, to_year)
    return services.get_coverage(start, end, limit, offset)


@app.get("/api/v1/insights")
def insights():
    return services.get_insights()
