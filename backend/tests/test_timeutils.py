"""Tests for UTC-aware timestamp parsing and canonicalisation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ingestion import timeutils


def test_parse_zulu_and_offset_agree():
    a = timeutils.parse_utc("2026-01-01T00:00:00Z")
    b = timeutils.parse_utc("2026-01-01T00:00:00+00:00")
    assert a == b == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_parse_non_utc_offset_is_converted_to_utc():
    # 01:00 at +01:00 is midnight UTC.
    dt = timeutils.parse_utc("2026-01-01T01:00:00+01:00")
    assert dt == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_parse_rejects_naive_timestamp():
    with pytest.raises(ValueError):
        timeutils.parse_utc("2026-01-01T00:00:00")


def test_parse_rejects_empty_and_garbage():
    with pytest.raises(ValueError):
        timeutils.parse_utc("")
    with pytest.raises(ValueError):
        timeutils.parse_utc("not-a-timestamp")


def test_canonical_form_drops_microseconds_and_normalises_offset():
    assert (
        timeutils.to_canonical_z("2026-01-31T23:30:00.500000+00:00")
        == "2026-01-31T23:30:00Z"
    )
    assert timeutils.to_canonical_z("2026-01-01T01:00:00+01:00") == "2026-01-01T00:00:00Z"


def test_parse_settlement_date():
    assert timeutils.parse_settlement_date("2026-01-15").isoformat() == "2026-01-15"


def test_in_target_window_is_half_open():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    # Start is inclusive.
    assert timeutils.in_target_window("2026-01-01T00:00:00Z", start, end)
    # Last January half-hour is in-window.
    assert timeutils.in_target_window("2026-01-31T23:30:00Z", start, end)
    # End (first February instant) is exclusive.
    assert not timeutils.in_target_window("2026-02-01T00:00:00Z", start, end)
    # December is out.
    assert not timeutils.in_target_window("2025-12-31T23:00:00Z", start, end)
