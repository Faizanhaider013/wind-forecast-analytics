"""Regression tests: a forecast vintage with a NULL generation value.

``normalize_forecast`` stores ``row.get("generation")`` without rejecting a
null, and the ``forecast_vintages.generation_mw`` column is nullable, so a
WINDFOR row that omits its generation is a legitimately storable vintage. These
tests lock in that none of the three builders crash on it (they previously
raised ``TypeError`` from ``float(None)``), and that such a vintage is excluded
from scoring rather than imputed, while valid vintages are still scored.
"""

from __future__ import annotations

from datetime import date

from app import analytics
from tests.conftest import insert_forecast, insert_hour_actual


NULL_TARGET = "2026-01-15T12:00:00Z"
GOOD_TARGET = "2026-01-15T13:00:00Z"
PUBLISH = "2026-01-14T09:00:00Z"


def _seed_null_and_good(conn):
    # Complete actuals for both hours.
    insert_hour_actual(conn, NULL_TARGET, 1000, 1000)  # mean 1000
    insert_hour_actual(conn, GOOD_TARGET, 900, 900)    # mean 900
    # One vintage with NULL generation (unscoreable) and one valid vintage.
    insert_forecast(conn, NULL_TARGET, PUBLISH, None)
    insert_forecast(conn, GOOD_TARGET, PUBLISH, 1100)  # error +200


def test_horizon_excludes_null_forecast_without_crashing(memory_db):
    _seed_null_and_good(memory_db)
    res = analytics.build_horizon(memory_db, date(2026, 1, 15), date(2026, 1, 15))
    assert res["excluded_null_forecast"] == 1
    # Only the valid vintage is scored; the null one is dropped, not imputed.
    assert res["total_scored_vintages"] == 1
    bucket = next(b for b in res["buckets"] if b["n"] > 0)
    assert bucket["bias_mw"] == 200.0  # 1100 - 900, the valid vintage only


def test_accuracy_treats_null_eligible_forecast_as_missing(memory_db):
    _seed_null_and_good(memory_db)
    acc = analytics.build_accuracy(memory_db, date(2026, 1, 15), date(2026, 1, 15), 10)
    # Only the valid hour is matched; the null-generation hour is not scored.
    assert acc["metrics"]["n"] == 1
    assert acc["metrics"]["mae_mw"] == 200.0  # |1100 - 900|
    # The null-generation hour counts toward missing-forecast coverage (it is
    # not a usable forecast), alongside the 22 hours with no vintage at all.
    assert acc["coverage"]["excluded_missing_forecast"] == 23


def test_decision_reports_null_forecast_as_unmatched(memory_db):
    _seed_null_and_good(memory_db)
    dec = analytics.build_decision(memory_db, date(2026, 1, 15), 10)
    null_p = next(p for p in dec["periods"] if p["hour_utc"] == NULL_TARGET)
    assert null_p["forecast_mw"] is None
    assert null_p["matched"] is False
    good_p = next(p for p in dec["periods"] if p["hour_utc"] == GOOD_TARGET)
    assert good_p["forecast_mw"] == 1100
    assert good_p["matched"] is True
    # The null-generation vintage is excluded from the forecast average (the
    # summary only aggregates present values), so the average is the valid one.
    assert dec["summary"]["forecast"]["avg_mw"] == 1100.0
    assert dec["summary"]["forecast"]["hours_with_forecast"] == 1
