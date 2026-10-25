"""Aggregation of half-hourly actuals into hourly means, without imputation."""

from __future__ import annotations

from datetime import datetime, timezone

from app import analytics
from tests.conftest import insert_actual, insert_hour_actual


WINDOW_START = datetime(2026, 1, 15, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 1, 16, tzinfo=timezone.utc)


def _means(conn):
    return analytics.hourly_actual_means(conn, WINDOW_START, WINDOW_END)


def test_hourly_mean_is_average_of_two_half_hours(memory_db):
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 1000, 2000)
    means = _means(memory_db)
    hour = means["2026-01-15T00:00:00Z"]
    assert hour.complete is True
    assert hour.n_half_hours == 2
    assert hour.mean_mw == 1500.0  # (1000 + 2000) / 2


def test_hour_with_one_half_hour_is_incomplete_and_not_imputed(memory_db):
    # Only the :00 half-hour present; :30 missing entirely.
    insert_actual(memory_db, "2026-01-15T03:00:00Z", 4000)
    means = _means(memory_db)
    hour = means["2026-01-15T03:00:00Z"]
    assert hour.complete is False
    assert hour.n_half_hours == 1
    assert hour.mean_mw is None  # never fabricated from a single observation


def test_hour_with_null_generation_half_is_incomplete(memory_db):
    # Row present but generation is NULL -> counts as not-present, incomplete.
    insert_hour_actual(memory_db, "2026-01-15T04:00:00Z", 5000, None)
    hour = _means(memory_db)["2026-01-15T04:00:00Z"]
    assert hour.n_half_hours == 1
    assert hour.complete is False
    assert hour.mean_mw is None


def test_missing_hour_absent_from_results(memory_db):
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 1000, 2000)
    means = _means(memory_db)
    # An hour with no rows at all is simply not present in the dict.
    assert "2026-01-15T05:00:00Z" not in means
