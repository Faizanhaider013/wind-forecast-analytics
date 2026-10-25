"""Integration tests for the decision and accuracy builders over a small DB."""

from __future__ import annotations

from datetime import date

from app import analytics
from tests.conftest import insert_actual, insert_forecast, insert_hour_actual


def _period(decision, hour):
    return next(p for p in decision["periods"] if p["hour_utc"] == hour)


def test_decision_matches_missing_and_incomplete(memory_db):
    # Hour 00:00 -- eligible forecast + complete actual -> matched.
    insert_forecast(memory_db, "2026-01-15T00:00:00Z", "2026-01-14T09:30:00Z", 200)
    insert_forecast(memory_db, "2026-01-15T00:00:00Z", "2026-01-14T11:00:00Z", 999)  # future
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 100, 300)  # mean 200
    # Hour 01:00 -- eligible forecast but incomplete actual (one half-hour).
    insert_forecast(memory_db, "2026-01-15T01:00:00Z", "2026-01-14T09:30:00Z", 250)
    insert_actual(memory_db, "2026-01-15T01:00:00Z", 250)
    # Hour 02:00 -- complete actual but no forecast at/before cutoff.
    insert_hour_actual(memory_db, "2026-01-15T02:00:00Z", 100, 100)

    dec = analytics.build_decision(memory_db, date(2026, 1, 15), 10)

    p0 = _period(dec, "2026-01-15T00:00:00Z")
    assert p0["forecast_mw"] == 200  # future vintage (999) never selected
    assert p0["forecast_publish_time"] == "2026-01-14T09:30:00Z"
    assert p0["actual_mean_mw"] == 200.0
    assert p0["error_mw"] == 0.0
    assert p0["matched"] is True

    p1 = _period(dec, "2026-01-15T01:00:00Z")
    assert p1["forecast_mw"] == 250
    assert p1["actual_complete"] is False
    assert p1["actual_mean_mw"] is None  # not imputed
    assert p1["error_mw"] is None
    assert p1["matched"] is False

    p2 = _period(dec, "2026-01-15T02:00:00Z")
    assert p2["forecast_mw"] is None
    assert p2["actual_complete"] is True
    assert p2["matched"] is False

    cov = dec["coverage"]
    assert cov["expected_hours"] == 24
    assert cov["matched_hours"] == 1
    assert "2026-01-15T02:00:00Z" in cov["missing_forecast_hours"]
    assert "2026-01-15T01:00:00Z" in cov["incomplete_actual_hours"]
    assert cov["fully_covered"] is False


def test_decision_summary_units_mw_and_mwh(memory_db):
    # Two fully matched hours; check MW averages and MWh totals.
    insert_forecast(memory_db, "2026-01-15T00:00:00Z", "2026-01-14T09:30:00Z", 1000)
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 800, 800)  # mean 800
    insert_forecast(memory_db, "2026-01-15T01:00:00Z", "2026-01-14T09:30:00Z", 2000)
    insert_hour_actual(memory_db, "2026-01-15T01:00:00Z", 1000, 1200)  # mean 1100

    dec = analytics.build_decision(memory_db, date(2026, 1, 15), 10)
    s = dec["summary"]
    assert s["forecast"]["avg_mw"] == 1500.0  # (1000 + 2000) / 2
    assert s["forecast"]["total_mwh"] == 3000.0  # 1000*1h + 2000*1h
    assert s["actual"]["avg_mw"] == 950.0  # (800 + 1100) / 2
    assert s["actual"]["total_mwh_hourly_basis"] == 1900.0
    # Native half-hourly energy: (800+800+1000+1200) * 0.5h = 1900 MWh.
    assert s["actual"]["total_mwh_halfhourly_basis"] == 1900.0


def test_accuracy_metrics_and_persistence_present(memory_db):
    # Delivery day 2026-01-15, one matched hour at 00:00.
    insert_forecast(memory_db, "2026-01-15T00:00:00Z", "2026-01-14T09:30:00Z", 500)
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 300, 300)  # mean 300
    # D-2 (2026-01-13) same hour complete actual -> persistence available.
    insert_hour_actual(memory_db, "2026-01-13T00:00:00Z", 400, 400)  # mean 400

    acc = analytics.build_accuracy(memory_db, date(2026, 1, 15), date(2026, 1, 15), 10)
    assert acc["metrics"]["n"] == 1
    assert acc["metrics"]["mae_mw"] == 200.0  # |500 - 300|
    assert acc["metrics"]["bias_mw"] == 200.0  # overprediction

    pers = acc["persistence_benchmark"]
    assert pers["included"] is True
    assert pers["n"] == 1
    assert pers["mae_mw"] == 100.0  # |400 - 300|


def test_accuracy_persistence_skill_uses_common_sample(memory_db):
    # Delivery 2026-01-01: matched, but its D-2 (2025-12-30) is absent -> NOT in
    # the persistence subset. Delivery 2026-01-03: matched AND has a D-2 actual
    # (2026-01-01) -> in the persistence subset.
    insert_forecast(memory_db, "2026-01-01T00:00:00Z", "2025-12-30T09:30:00Z", 500)
    insert_hour_actual(memory_db, "2026-01-01T00:00:00Z", 300, 300)  # mean 300
    insert_forecast(memory_db, "2026-01-03T00:00:00Z", "2026-01-02T09:30:00Z", 450)
    insert_hour_actual(memory_db, "2026-01-03T00:00:00Z", 400, 400)  # mean 400

    acc = analytics.build_accuracy(memory_db, date(2026, 1, 1), date(2026, 1, 3), 10)
    # Full model set spans both hours: MAE = (|500-300| + |450-400|) / 2 = 125.
    assert acc["metrics"]["n"] == 2
    assert acc["metrics"]["mae_mw"] == 125.0

    pb = acc["persistence_benchmark"]
    # Persistence covers only the 2026-01-03 hour (D-2 = 2026-01-01, mean 300).
    assert pb["n"] == 1
    assert pb["mae_mw"] == 100.0  # |300 - 400|
    # Paired model MAE is over that SAME single hour: |450 - 400| = 50 (not 125).
    assert pb["model_mae_mw_same_sample"] == 50.0
    assert pb["skill_mae_percent"] == round((1 - 50 / 100) * 100, 3)  # 50.0


def test_accuracy_persistence_omitted_without_prior_day(memory_db):
    insert_forecast(memory_db, "2026-01-15T00:00:00Z", "2026-01-14T09:30:00Z", 500)
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 300, 300)
    acc = analytics.build_accuracy(memory_db, date(2026, 1, 15), date(2026, 1, 15), 10)
    assert acc["persistence_benchmark"]["included"] is False
    assert acc["persistence_benchmark"]["n"] == 0
    assert "omitted" in acc["persistence_benchmark"]["note"]


def test_accuracy_reports_exclusions(memory_db):
    # One matched hour, rest of the day missing -> exclusions reported.
    insert_forecast(memory_db, "2026-01-15T00:00:00Z", "2026-01-14T09:30:00Z", 500)
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 300, 300)
    acc = analytics.build_accuracy(memory_db, date(2026, 1, 15), date(2026, 1, 15), 10)
    cov = acc["coverage"]
    assert cov["expected_hours"] == 24
    assert cov["matched_hours"] == 1
    assert cov["excluded_missing_forecast"] == 23
    assert cov["excluded_incomplete_actual"] == 23
    assert cov["matched_fraction"] == round(1 / 24, 5)


def test_available_dates_distinguishes_complete(memory_db):
    # A complete-actuals day needs 48 half-hours; here we add only 2 -> partial.
    insert_hour_actual(memory_db, "2026-01-15T00:00:00Z", 100, 100)
    insert_forecast(memory_db, "2026-01-15T00:00:00Z", "2026-01-14T09:30:00Z", 100)
    out = analytics.available_dates(memory_db)
    entry = next(e for e in out["dates"] if e["date"] == "2026-01-15")
    assert entry["actuals"]["half_hour_periods"] == 2
    assert entry["actuals"]["complete"] is False
    assert entry["forecasts"]["complete"] is False
    assert entry["complete"] is False
