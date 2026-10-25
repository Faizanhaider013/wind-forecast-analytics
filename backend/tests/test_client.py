"""Tests for the Elexon HTTP client: success, retries, and error handling.

All behaviour is exercised through the injectable transport -- no live HTTP.
"""

from __future__ import annotations

import pytest

from app.ingestion import config
from app.ingestion.elexon_client import ElexonAPIError, ElexonClient, HttpResponse
from tests.conftest import FakeTransport, make_fuelhh_row, make_windfor_row


def _client(transport: FakeTransport) -> ElexonClient:
    # sleep is a no-op so retry tests run instantly.
    return ElexonClient(transport=transport, backoff=0.0, sleep=lambda _s: None)


def test_fetch_fuelhh_parses_data_and_sends_expected_params():
    transport = FakeTransport(
        lambda url: transport.json_response(
            [make_fuelhh_row("2026-01-01T00:00:00Z", 1, 13756)]
        )
    )
    client = _client(transport)
    rows = client.fetch_fuelhh_wind("2026-01-01", "2026-01-07")
    assert rows[0]["generation"] == 13756
    url = transport.calls[0]
    assert "settlementDateFrom=2026-01-01" in url
    assert "settlementDateTo=2026-01-07" in url
    assert "fuelType=WIND" in url


def test_fetch_windfor_parses_data():
    transport = FakeTransport(
        lambda url: transport.json_response(
            [make_windfor_row("2026-01-01T00:00:00Z", "2025-12-31T09:30:00Z", 5000)]
        )
    )
    rows = _client(transport).fetch_windfor(
        "2025-12-29T00:00:00Z", "2026-01-05T00:00:00Z"
    )
    assert rows[0]["generation"] == 5000


def test_retries_on_500_then_succeeds():
    seq = [
        HttpResponse(500, b"server error"),
        None,  # placeholder replaced below
    ]

    def responder(url):
        item = seq.pop(0)
        if item is None:
            return transport.json_response([make_windfor_row(
                "2026-01-01T00:00:00Z", "2025-12-31T09:30:00Z", 5000)])
        return item

    transport = FakeTransport(responder)
    rows = _client(transport).fetch_windfor("a", "b")
    assert len(rows) == 1
    assert len(transport.calls) == 2  # one failure, one success


def test_retries_exhausted_raises():
    transport = FakeTransport(lambda url: HttpResponse(503, b"down"))
    with pytest.raises(ElexonAPIError):
        _client(transport).fetch_fuelhh_wind("2026-01-01", "2026-01-07")
    assert len(transport.calls) == config.HTTP_MAX_ATTEMPTS


def test_non_retryable_400_raises_with_body():
    body = (
        b'{"errors":{"":["The date range ... inclusive must not exceed 7 days"]}}'
    )
    transport = FakeTransport(lambda url: HttpResponse(400, body))
    with pytest.raises(ElexonAPIError) as exc:
        _client(transport).fetch_fuelhh_wind("2026-01-01", "2026-01-31")
    assert "must not exceed 7 days" in str(exc.value)
    assert len(transport.calls) == 1  # not retried


def test_network_error_is_retried_then_raised():
    transport = FakeTransport(lambda url: OSError("connection reset"))
    with pytest.raises(ElexonAPIError):
        _client(transport).fetch_windfor("a", "b")
    assert len(transport.calls) == config.HTTP_MAX_ATTEMPTS


def test_malformed_json_raises():
    transport = FakeTransport(lambda url: HttpResponse(200, b"not json{"))
    with pytest.raises(ElexonAPIError):
        _client(transport).fetch_windfor("a", "b")


def test_missing_data_key_raises():
    transport = FakeTransport(lambda url: HttpResponse(200, b'{"foo":[]}'))
    with pytest.raises(ElexonAPIError):
        _client(transport).fetch_fuelhh_wind("2026-01-01", "2026-01-07")
