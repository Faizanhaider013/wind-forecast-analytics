"""Tests that actuals stay half-hourly and forecasts stay hourly.

The ingestion must never duplicate an hourly forecast into half-hourly slots or
otherwise fabricate records: what is stored matches the source granularity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ingestion import pipeline, storage, timeutils
from tests.conftest import make_fuelhh_row, make_windfor_row


def test_actuals_are_half_hourly_48_per_day(memory_db):
    rows = []
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for period in range(1, 49):
        rows.append(
            make_fuelhh_row(timeutils.to_canonical_z(t), period, 13000 + period)
        )
        t += timedelta(minutes=30)
    storage.upsert_actuals(memory_db, [pipeline.normalize_actual(r) for r in rows])

    stored = [
        r["target_start_time"]
        for r in memory_db.execute(
            "SELECT target_start_time FROM actuals ORDER BY target_start_time"
        ).fetchall()
    ]
    assert len(stored) == 48
    # Consecutive targets are exactly 30 minutes apart.
    deltas = {
        timeutils.parse_utc(b) - timeutils.parse_utc(a)
        for a, b in zip(stored, stored[1:])
    }
    assert deltas == {timedelta(minutes=30)}


def test_forecasts_are_hourly_and_not_expanded(memory_db):
    publish = "2026-01-01T09:30:00Z"
    rows = []
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for _ in range(24):
        rows.append(make_windfor_row(timeutils.to_canonical_z(t), publish, 5000))
        t += timedelta(hours=1)
    storage.upsert_forecast_vintages(
        memory_db, [pipeline.normalize_forecast(r) for r in rows]
    )

    stored = [
        r["target_start_time"]
        for r in memory_db.execute(
            "SELECT target_start_time FROM forecast_vintages ORDER BY target_start_time"
        ).fetchall()
    ]
    # 24 hourly rows in, 24 hourly rows out -- no half-hourly expansion.
    assert len(stored) == 24
    deltas = {
        timeutils.parse_utc(b) - timeutils.parse_utc(a)
        for a, b in zip(stored, stored[1:])
    }
    assert deltas == {timedelta(hours=1)}
    # No fabricated :30 target appears.
    assert all(ts.endswith(":00:00Z") for ts in stored)
