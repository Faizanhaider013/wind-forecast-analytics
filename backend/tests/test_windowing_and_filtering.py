"""Tests for request windowing and target-date filtering to January 2026."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.ingestion import config, pipeline, timeutils
from tests.conftest import make_windfor_row


JAN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
JAN_END = datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_settlement_windows_cover_january_within_limit():
    windows = pipeline.settlement_date_windows(date(2026, 1, 1), date(2026, 1, 31))
    # Each window must respect the API's 7-day inclusive limit.
    for lo, hi in windows:
        span = (date.fromisoformat(hi) - date.fromisoformat(lo)).days + 1
        assert span <= config.MAX_WINDOW_DAYS
    # Windows must be contiguous and span the whole month exactly once.
    assert windows[0][0] == "2026-01-01"
    assert windows[-1][1] == "2026-01-31"
    for (lo, hi), (next_lo, _) in zip(windows, windows[1:]):
        assert date.fromisoformat(next_lo) == date.fromisoformat(hi) + timedelta(days=1)


def test_publish_windows_respect_seven_day_limit_and_cover_range():
    start = JAN_START - timedelta(days=3)
    end = JAN_END + timedelta(days=1)
    windows = pipeline.publish_time_windows(start, end)
    for lo, hi in windows:
        span = timeutils.parse_utc(hi) - timeutils.parse_utc(lo)
        assert span <= timedelta(days=config.MAX_WINDOW_DAYS)
    assert timeutils.parse_utc(windows[0][0]) == start
    assert timeutils.parse_utc(windows[-1][1]) == end


def test_forecast_filter_keeps_only_january_targets():
    # One vintage covering Dec 31 2025 .. Feb 1 2026 hourly.
    rows = []
    t = datetime(2025, 12, 31, 20, tzinfo=timezone.utc)
    publish = "2025-12-31T09:30:00Z"
    while t <= datetime(2026, 2, 1, 2, tzinfo=timezone.utc):
        rows.append(make_windfor_row(timeutils.to_canonical_z(t), publish, 5000))
        t += timedelta(hours=1)

    kept = [
        pipeline.normalize_forecast(r)
        for r in rows
        if timeutils.in_target_window(r["startTime"], JAN_START, JAN_END)
    ]
    targets = [k["target_start_time"] for k in kept]
    assert "2026-01-01T00:00:00Z" in targets
    assert "2026-01-31T23:00:00Z" in targets
    # Nothing before January or in February leaked in.
    assert all("2026-01" == t[:7] for t in targets)
    assert "2025-12-31T20:00:00Z" not in targets
    assert "2026-02-01T00:00:00Z" not in targets
