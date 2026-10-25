"""Cutoff computation, UK daylight-saving handling, and cutoff enforcement."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app import analytics
from app.ingestion import timeutils
from tests.conftest import insert_forecast


def test_cutoff_winter_is_utc():
    # January: Europe/London == UTC, so 10:00 local == 10:00 UTC.
    cutoff = analytics.compute_cutoff_utc(date(2026, 1, 15), 10)
    assert timeutils.to_canonical_z(cutoff) == "2026-01-14T10:00:00Z"


def test_cutoff_summer_is_bst_offset():
    # July: BST (UTC+1), so 10:00 local the day before == 09:00 UTC.
    cutoff = analytics.compute_cutoff_utc(date(2026, 7, 15), 10)
    assert timeutils.to_canonical_z(cutoff) == "2026-07-14T09:00:00Z"


def test_cutoff_custom_hour():
    cutoff = analytics.compute_cutoff_utc(date(2026, 1, 15), 6)
    assert timeutils.to_canonical_z(cutoff) == "2026-01-14T06:00:00Z"


def test_cutoff_hour_out_of_range_raises():
    with pytest.raises(ValueError):
        analytics.compute_cutoff_utc(date(2026, 1, 15), 24)


def test_delivery_window_winter_is_24_hours():
    start, end = analytics.delivery_day_utc_window(date(2026, 1, 15))
    assert timeutils.to_canonical_z(start) == "2026-01-15T00:00:00Z"
    assert timeutils.to_canonical_z(end) == "2026-01-16T00:00:00Z"
    assert (end - start).total_seconds() == 24 * 3600


def test_delivery_window_spring_forward_is_23_hours():
    # Clocks go forward on 2026-03-29 (01:00 -> 02:00 BST): a 23-hour local day.
    start, end = analytics.delivery_day_utc_window(date(2026, 3, 29))
    assert timeutils.to_canonical_z(start) == "2026-03-29T00:00:00Z"
    assert timeutils.to_canonical_z(end) == "2026-03-29T23:00:00Z"
    assert (end - start).total_seconds() == 23 * 3600


def test_delivery_window_fall_back_is_25_hours():
    # Clocks go back on 2026-10-25 (02:00 -> 01:00 GMT): a 25-hour local day.
    start, end = analytics.delivery_day_utc_window(date(2026, 10, 25))
    assert timeutils.to_canonical_z(start) == "2026-10-24T23:00:00Z"
    assert timeutils.to_canonical_z(end) == "2026-10-26T00:00:00Z"
    assert (end - start).total_seconds() == 25 * 3600


def test_cutoff_enforced_never_uses_future_vintage(memory_db):
    target = "2026-01-15T00:00:00Z"
    cutoff = datetime(2026, 1, 14, 10, tzinfo=timezone.utc)
    # Two eligible (<= cutoff) and one published after the cutoff.
    insert_forecast(memory_db, target, "2026-01-13T09:30:00Z", 100)
    insert_forecast(memory_db, target, "2026-01-14T09:30:00Z", 200)  # latest eligible
    insert_forecast(memory_db, target, "2026-01-14T11:30:00Z", 999)  # after cutoff
    start = datetime(2026, 1, 15, tzinfo=timezone.utc)
    end = datetime(2026, 1, 16, tzinfo=timezone.utc)
    selected = analytics.select_eligible_forecasts(memory_db, start, end, cutoff)
    assert selected[target] == ("2026-01-14T09:30:00Z", 200)


def test_cutoff_exactly_at_publish_time_is_included(memory_db):
    target = "2026-01-15T00:00:00Z"
    # Vintage published exactly at the cutoff instant must be eligible (<=).
    insert_forecast(memory_db, target, "2026-01-14T10:00:00Z", 321)
    cutoff = datetime(2026, 1, 14, 10, tzinfo=timezone.utc)
    start = datetime(2026, 1, 15, tzinfo=timezone.utc)
    end = datetime(2026, 1, 16, tzinfo=timezone.utc)
    selected = analytics.select_eligible_forecasts(memory_db, start, end, cutoff)
    assert selected[target][1] == 321
