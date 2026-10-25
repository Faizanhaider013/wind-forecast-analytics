"""Shared test fixtures and HTTP stubs.

All tests run fully offline: the Elexon client is driven through an injectable
transport, never a live request.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable

import pytest

from app.ingestion import storage
from app.ingestion.elexon_client import HttpResponse


class FakeTransport:
    """A scripted transport for :class:`ElexonClient`.

    Configure it either with a fixed response, a sequence of responses to return
    in order, or a function of the URL. Raising values in the queue are raised,
    which lets tests simulate network errors.
    """

    def __init__(self, responder: Callable[[str], object] | None = None):
        self.calls: list[str] = []
        self._responder = responder

    def json_response(self, rows: list[dict], status: int = 200) -> HttpResponse:
        body = json.dumps({"data": rows}).encode("utf-8")
        return HttpResponse(status=status, body=body)

    def __call__(self, url: str, timeout: float) -> HttpResponse:
        self.calls.append(url)
        assert self._responder is not None, "FakeTransport needs a responder"
        result = self._responder(url)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def memory_db() -> sqlite3.Connection:
    """An in-memory SQLite connection with the schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(storage.SCHEMA)
    yield conn
    conn.close()


def make_fuelhh_row(start_time: str, period: int, generation: int) -> dict:
    """Build a FUELHH-shaped row as the API returns it."""
    return {
        "dataset": "FUELHH",
        "publishTime": start_time,
        "startTime": start_time,
        "settlementDate": start_time[:10],
        "settlementPeriod": period,
        "fuelType": "WIND",
        "generation": generation,
    }


def make_windfor_row(start_time: str, publish_time: str, generation: int) -> dict:
    """Build a WINDFOR-shaped row as the API returns it."""
    return {
        "dataset": "WINDFOR",
        "publishTime": publish_time,
        "startTime": start_time,
        "generation": generation,
    }


# --- direct DB-row inserts for Phase 2 analytics tests -----------------------


def insert_actual(
    conn,
    target_start_time: str,
    generation_mw,
    *,
    fuel_type: str = "WIND",
    settlement_period: int = 1,
) -> None:
    """Insert one half-hourly actual row (generation_mw may be None)."""
    conn.execute(
        "INSERT INTO actuals (target_start_time, settlement_date, "
        "settlement_period, fuel_type, generation_mw, dataset, publish_time, "
        "ingested_at) VALUES (?, ?, ?, ?, ?, 'FUELHH', ?, '2026-10-25T00:00:00Z')",
        (
            target_start_time,
            target_start_time[:10],
            settlement_period,
            fuel_type,
            generation_mw,
            target_start_time,
        ),
    )
    conn.commit()


def insert_forecast(
    conn, target_start_time: str, publish_time: str, generation_mw: int
) -> None:
    """Insert one forecast vintage row."""
    conn.execute(
        "INSERT INTO forecast_vintages (target_start_time, publish_time, "
        "generation_mw, dataset, ingested_at) VALUES (?, ?, ?, 'WINDFOR', "
        "'2026-10-25T00:00:00Z')",
        (target_start_time, publish_time, generation_mw),
    )
    conn.commit()


def insert_hour_actual(conn, hour_utc: str, gen_00: int, gen_30, *, period: int = 1) -> None:
    """Insert the two half-hourly actuals for a UTC hour (``...THH:00:00Z``).

    ``gen_30`` may be None to simulate a missing/partial hour.
    """
    insert_actual(conn, hour_utc, gen_00, settlement_period=period)
    half = f"{hour_utc[:13]}:30:00Z"
    insert_actual(conn, half, gen_30, settlement_period=period + 1)
