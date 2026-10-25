"""Tests for idempotent dedup of actuals and forecast-vintage retention."""

from __future__ import annotations

from app.ingestion import pipeline, storage
from tests.conftest import make_fuelhh_row, make_windfor_row


def _norm_actuals(rows):
    return [pipeline.normalize_actual(r) for r in rows]


def _norm_forecasts(rows):
    return [pipeline.normalize_forecast(r) for r in rows]


def test_actuals_reingest_is_idempotent(memory_db):
    rows = _norm_actuals(
        [
            make_fuelhh_row("2026-01-01T00:00:00Z", 1, 13756),
            make_fuelhh_row("2026-01-01T00:30:00Z", 2, 13873),
        ]
    )
    first = storage.upsert_actuals(memory_db, rows)
    assert (first.inserted, first.updated, first.duplicates) == (2, 0, 0)

    # Re-ingesting identical data inserts nothing and counts duplicates.
    second = storage.upsert_actuals(memory_db, rows)
    assert (second.inserted, second.updated, second.duplicates) == (0, 0, 2)

    n = memory_db.execute("SELECT COUNT(*) FROM actuals").fetchone()[0]
    assert n == 2


def test_actual_revision_updates_in_place(memory_db):
    storage.upsert_actuals(
        memory_db, _norm_actuals([make_fuelhh_row("2026-01-01T00:00:00Z", 1, 13756)])
    )
    revised = storage.upsert_actuals(
        memory_db, _norm_actuals([make_fuelhh_row("2026-01-01T00:00:00Z", 1, 13800)])
    )
    assert (revised.inserted, revised.updated, revised.duplicates) == (0, 1, 0)
    val = memory_db.execute(
        "SELECT generation_mw FROM actuals WHERE settlement_period = 1"
    ).fetchone()[0]
    assert val == 13800
    assert memory_db.execute("SELECT COUNT(*) FROM actuals").fetchone()[0] == 1


def test_forecast_vintages_are_all_retained(memory_db):
    target = "2026-01-15T12:00:00Z"
    # Three successive publications for the SAME target time.
    rows = _norm_forecasts(
        [
            make_windfor_row(target, "2026-01-13T09:30:00Z", 4800),
            make_windfor_row(target, "2026-01-14T09:30:00Z", 5100),
            make_windfor_row(target, "2026-01-15T09:30:00Z", 5300),
        ]
    )
    counts = storage.upsert_forecast_vintages(memory_db, rows)
    assert counts.inserted == 3

    # Every vintage for the target is preserved; none overwritten.
    stored = memory_db.execute(
        "SELECT publish_time, generation_mw FROM forecast_vintages "
        "WHERE target_start_time = ? ORDER BY publish_time",
        (target,),
    ).fetchall()
    assert [r["generation_mw"] for r in stored] == [4800, 5100, 5300]


def test_forecast_reingest_same_vintage_is_duplicate(memory_db):
    target = "2026-01-15T12:00:00Z"
    rows = _norm_forecasts([make_windfor_row(target, "2026-01-14T09:30:00Z", 5100)])
    storage.upsert_forecast_vintages(memory_db, rows)
    again = storage.upsert_forecast_vintages(memory_db, rows)
    assert (again.inserted, again.updated, again.duplicates) == (0, 0, 1)
    assert memory_db.execute(
        "SELECT COUNT(*) FROM forecast_vintages"
    ).fetchone()[0] == 1
