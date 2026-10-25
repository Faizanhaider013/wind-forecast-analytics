"""API-layer tests via FastAPI's TestClient (in-process, no network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import api
from app.db import DatabaseUnavailable, connect_readonly
from app.ingestion import storage
from app.main import DEFAULT_CORS_ORIGINS, app, cors_origins
from tests.conftest import insert_forecast, insert_hour_actual


def test_cors_origins_defaults_to_dev_origin():
    # No env set -> the existing local dev origin, unchanged behaviour.
    assert cors_origins(None) == [DEFAULT_CORS_ORIGINS]


def test_cors_origins_parses_comma_separated_list():
    parsed = cors_origins("https://app.example.com, https://admin.example.com ,")
    assert parsed == ["https://app.example.com", "https://admin.example.com"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    """A tiny on-disk DB wired into the API's read-only connector."""
    db_path = tmp_path / "wind.db"
    conn = storage.connect(db_path)
    insert_hour_actual(conn, "2026-01-15T00:00:00Z", 100, 300)  # actual mean 200
    insert_forecast(conn, "2026-01-15T00:00:00Z", "2026-01-14T09:30:00Z", 200)
    insert_forecast(conn, "2026-01-15T00:00:00Z", "2026-01-14T11:00:00Z", 999)  # future
    conn.close()
    monkeypatch.setattr(api, "connect_readonly", lambda: connect_readonly(db_path))
    return db_path


def test_health_still_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_decision_invalid_date_400(client):
    r = client.get("/api/decision/2026-13-40")
    assert r.status_code == 400
    assert "invalid delivery_date" in r.json()["detail"]


def test_decision_cutoff_out_of_range_422(client):
    # FastAPI Query validation (le=23) rejects before handler logic.
    r = client.get("/api/decision/2026-01-15", params={"cutoff_hour": 25})
    assert r.status_code == 422


def test_accuracy_bad_from_400(client):
    r = client.get("/api/accuracy", params={"from": "nope", "to": "2026-01-31"})
    assert r.status_code == 400


def test_accuracy_to_before_from_400(client):
    r = client.get("/api/accuracy", params={"from": "2026-01-31", "to": "2026-01-01"})
    assert r.status_code == 400


def test_horizon_to_before_from_400(client):
    # The by-horizon endpoint must enforce the same date-order rule as /accuracy.
    r = client.get(
        "/api/accuracy/by-horizon", params={"from": "2026-01-31", "to": "2026-01-01"}
    )
    assert r.status_code == 400


def test_horizon_bad_date_400(client):
    r = client.get("/api/accuracy/by-horizon", params={"from": "nope", "to": "2026-01-31"})
    assert r.status_code == 400


def test_missing_database_returns_503(client, monkeypatch, tmp_path):
    def _raise():
        raise DatabaseUnavailable("database not found")

    monkeypatch.setattr(api, "connect_readonly", _raise)
    r = client.get("/api/available-dates")
    assert r.status_code == 503
    assert "database not found" in r.json()["detail"]


def test_available_dates_ok(client, patched_db):
    r = client.get("/api/available-dates")
    assert r.status_code == 200
    assert r.json()["summary"]["total_dates"] == 1


def test_decision_ok_selects_eligible_vintage(client, patched_db):
    r = client.get("/api/decision/2026-01-15", params={"cutoff_hour": 10})
    assert r.status_code == 200
    body = r.json()
    matched = [p for p in body["periods"] if p["matched"]]
    assert len(matched) == 1
    # The future vintage (999) is never selected.
    assert matched[0]["forecast_mw"] == 200
    assert matched[0]["error_mw"] == 0.0
    assert body["cutoff"]["utc_time"] == "2026-01-14T10:00:00Z"


def test_accuracy_and_horizon_ok(client, patched_db):
    acc = client.get(
        "/api/accuracy", params={"from": "2026-01-15", "to": "2026-01-15"}
    )
    assert acc.status_code == 200
    assert acc.json()["metrics"]["n"] == 1

    hz = client.get(
        "/api/accuracy/by-horizon", params={"from": "2026-01-15", "to": "2026-01-15"}
    )
    assert hz.status_code == 200
    # Both vintages (eligible + future) are scored in the no-cutoff horizon view.
    assert hz.json()["total_scored_vintages"] == 2
    assert hz.json()["cutoff_applied"] is False


def test_defaults_cover_january(client, patched_db):
    # No query params -> defaults to the January 2026 range.
    r = client.get("/api/accuracy")
    assert r.status_code == 200
    assert r.json()["from"] == "2026-01-01"
    assert r.json()["to"] == "2026-01-31"
