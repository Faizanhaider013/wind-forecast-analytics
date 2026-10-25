"""Lead-time (horizon) bucketing, including negative lead and cutoff restriction."""

from __future__ import annotations

from datetime import date

from app import analytics
from tests.conftest import insert_forecast, insert_hour_actual


TARGET = "2026-01-15T12:00:00Z"


def _seed(conn):
    # Complete hourly actual: mean = 1000.
    insert_hour_actual(conn, TARGET, 1000, 1000)
    # Forecasts (all forecast_mw = 1200 -> error +200) at varied lead times:
    insert_forecast(conn, TARGET, "2026-01-15T13:00:00Z", 1200)  # lead -1h  -> <0h
    insert_forecast(conn, TARGET, "2026-01-15T10:00:00Z", 1200)  # lead +2h  -> 0-6h
    insert_forecast(conn, TARGET, "2026-01-14T12:00:00Z", 1200)  # lead +24h -> 24-36h
    insert_forecast(conn, TARGET, "2026-01-13T00:00:00Z", 1200)  # lead +60h -> 48h+


def _bucket(result, name):
    return next(b for b in result["buckets"] if b["bucket"] == name)


def test_lead_time_buckets_and_counts(memory_db):
    _seed(memory_db)
    res = analytics.build_horizon(memory_db, date(2026, 1, 15), date(2026, 1, 15))
    assert res["cutoff_applied"] is False
    assert res["total_scored_vintages"] == 4
    assert _bucket(res, "<0h")["n"] == 1
    assert _bucket(res, "0-6h")["n"] == 1
    assert _bucket(res, "24-36h")["n"] == 1
    assert _bucket(res, "48h+")["n"] == 1
    # Each scored vintage has error forecast-actual = 1200-1000 = +200.
    assert _bucket(res, "0-6h")["mae_mw"] == 200.0
    assert _bucket(res, "0-6h")["bias_mw"] == 200.0
    # An empty bucket reports n=0 and null metrics.
    assert _bucket(res, "6-12h")["n"] == 0
    assert _bucket(res, "6-12h")["mae_mw"] is None


def test_actual_incomplete_hour_is_not_scored(memory_db):
    # Only one half-hour present -> the hour is incomplete, so no vintage scores.
    insert_hour_actual(memory_db, TARGET, 1000, None)
    insert_forecast(memory_db, TARGET, "2026-01-14T12:00:00Z", 1200)
    res = analytics.build_horizon(memory_db, date(2026, 1, 15), date(2026, 1, 15))
    assert res["total_scored_vintages"] == 0


def test_cutoff_restriction_excludes_future_vintages(memory_db):
    _seed(memory_db)
    # Cutoff = 2026-01-14 10:00 London (UTC in winter). Only the 2026-01-13
    # publication is at/ before it; the other three are excluded.
    res = analytics.build_horizon(
        memory_db, date(2026, 1, 15), date(2026, 1, 15), cutoff_hour=10
    )
    assert res["cutoff_applied"] is True
    assert res["excluded_after_cutoff"] == 3
    assert res["total_scored_vintages"] == 1
    assert _bucket(res, "48h+")["n"] == 1
