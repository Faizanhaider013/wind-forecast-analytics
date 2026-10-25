"""FastAPI routes for the Phase 2 decision and accuracy API.

Thin HTTP layer: it validates inputs, opens a read-only connection, delegates to
:mod:`app.analytics`, and maps errors to useful HTTP status codes. All date
inputs are validated; bad input yields 400, a missing database yields 503.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from . import analytics
from .db import DatabaseUnavailable, connect_readonly

router = APIRouter(prefix="/api")

# Default accuracy range: the ingested January 2026 delivery month.
DEFAULT_FROM = "2026-01-01"
DEFAULT_TO = "2026-01-31"


def _parse_date_or_400(value: str, field: str) -> date:
    try:
        return analytics.parse_date(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}: {exc}") from exc


def _validate_cutoff_or_400(cutoff_hour: int) -> int:
    if not 0 <= cutoff_hour <= 23:
        raise HTTPException(
            status_code=400, detail="cutoff_hour must be between 0 and 23"
        )
    return cutoff_hour


def _open_or_503():
    try:
        return connect_readonly()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/available-dates")
def get_available_dates() -> dict:
    """Dates with actuals/forecasts and their coverage completeness."""
    conn = _open_or_503()
    try:
        return analytics.available_dates(conn)
    finally:
        conn.close()


@router.get("/decision/{delivery_date}")
def get_decision(
    delivery_date: str,
    cutoff_hour: int = Query(
        analytics.DEFAULT_CUTOFF_HOUR,
        ge=0,
        le=23,
        description="Cutoff hour in Europe/London on the day before delivery "
        "(default 10 = 10:00 UK time).",
    ),
) -> dict:
    """Day-ahead hourly forecast vs actual for one delivery date."""
    d = _parse_date_or_400(delivery_date, "delivery_date")
    _validate_cutoff_or_400(cutoff_hour)
    conn = _open_or_503()
    try:
        return analytics.build_decision(conn, d, cutoff_hour)
    finally:
        conn.close()


@router.get("/accuracy")
def get_accuracy(
    from_: str = Query(DEFAULT_FROM, alias="from", description="Start date YYYY-MM-DD."),
    to: str = Query(DEFAULT_TO, description="End date YYYY-MM-DD (inclusive)."),
    cutoff_hour: int = Query(analytics.DEFAULT_CUTOFF_HOUR, ge=0, le=23),
) -> dict:
    """Forecast accuracy metrics over a date range (day-ahead selection)."""
    from_date = _parse_date_or_400(from_, "from")
    to_date = _parse_date_or_400(to, "to")
    if to_date < from_date:
        raise HTTPException(status_code=400, detail="'to' must not be before 'from'")
    _validate_cutoff_or_400(cutoff_hour)
    conn = _open_or_503()
    try:
        return analytics.build_accuracy(conn, from_date, to_date, cutoff_hour)
    finally:
        conn.close()


@router.get("/accuracy/by-horizon")
def get_accuracy_by_horizon(
    from_: str = Query(DEFAULT_FROM, alias="from", description="Start date YYYY-MM-DD."),
    to: str = Query(DEFAULT_TO, description="End date YYYY-MM-DD (inclusive)."),
    cutoff_hour: int | None = Query(
        None,
        ge=0,
        le=23,
        description="Optional. If set, restricts to vintages available at each "
        "target's day-ahead cutoff (Europe/London, day before). Omit for the "
        "full horizon curve across all vintages.",
    ),
) -> dict:
    """Forecast error grouped by lead-time (horizon) bucket across all vintages."""
    from_date = _parse_date_or_400(from_, "from")
    to_date = _parse_date_or_400(to, "to")
    if to_date < from_date:
        raise HTTPException(status_code=400, detail="'to' must not be before 'from'")
    conn = _open_or_503()
    try:
        return analytics.build_horizon(conn, from_date, to_date, cutoff_hour)
    finally:
        conn.close()
