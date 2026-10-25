"""End-to-end ingestion over a small window using a scripted transport.

Exercises windowing -> fetch -> raw caching -> target filtering -> upsert ->
coverage, all offline.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from app.ingestion import pipeline, storage, timeutils
from app.ingestion.elexon_client import ElexonClient
from tests.conftest import FakeTransport, make_fuelhh_row, make_windfor_row


def _qs(url: str) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))


def _responder_factory(transport: FakeTransport):
    """Return a URL responder that synthesises realistic FUELHH / WINDFOR data."""

    def responder(url: str):
        params = _qs(url)
        if "FUELHH" in url:
            lo = datetime.fromisoformat(params["settlementDateFrom"]).replace(
                tzinfo=timezone.utc
            )
            hi = datetime.fromisoformat(params["settlementDateTo"]).replace(
                tzinfo=timezone.utc
            )
            rows = []
            day = lo
            while day <= hi:
                for period in range(48):
                    t = day + timedelta(minutes=30 * period)
                    rows.append(
                        make_fuelhh_row(timeutils.to_canonical_z(t), period + 1, 10000 + period)
                    )
                day += timedelta(days=1)
            return transport.json_response(rows)

        # WINDFOR: emit two vintages per publish window, each covering a 3-day
        # hourly horizon starting at the window's "from" instant.
        pub_from = timeutils.parse_utc(params["publishDateTimeFrom"])
        rows = []
        for vintage_offset in (0, 12):
            publish = timeutils.to_canonical_z(pub_from + timedelta(hours=vintage_offset))
            for hour in range(72):
                target = pub_from + timedelta(hours=hour)
                rows.append(
                    make_windfor_row(timeutils.to_canonical_z(target), publish, 5000 + hour)
                )
        return transport.json_response(rows)

    return responder


def test_ingest_actuals_and_forecasts_over_two_days(tmp_path, memory_db):
    transport = FakeTransport()
    transport._responder = _responder_factory(transport)
    client = ElexonClient(transport=transport, backoff=0.0, sleep=lambda _s: None)

    window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 1, 3, tzinfo=timezone.utc)  # 2-day window

    a = pipeline.ingest_actuals(
        memory_db, client, window_start, window_end, data_dir=tmp_path
    )
    f = pipeline.ingest_forecasts(
        memory_db, client, window_start, window_end, lookback_days=1, data_dir=tmp_path
    )

    # Actuals: 2 days x 48 periods, all kept, all inserted.
    assert a.counts.inserted == 96
    assert a.kept == 96
    assert a.malformed == 0

    # Forecasts: only in-window targets kept; every row has a Jan 1-2 target.
    stored_targets = memory_db.execute(
        "SELECT DISTINCT target_start_time FROM forecast_vintages"
    ).fetchall()
    assert all(window_start <= timeutils.parse_utc(r[0]) < window_end for r in stored_targets)
    assert f.counts.inserted > 0

    # Raw responses were cached to disk under the dataset folders.
    assert (tmp_path / "raw" / "FUELHH").exists()
    assert (tmp_path / "raw" / "WINDFOR").exists()
    cached = list((tmp_path / "raw" / "FUELHH").glob("*.json"))
    assert cached and "data" in json.loads(cached[0].read_text())

    # Coverage reflects the stored rows.
    cov = storage.coverage_for_window(memory_db, window_start, window_end)
    assert cov.actual_periods == 96
    assert cov.forecast_distinct_targets == 48  # 2 days x 24 hourly targets
    assert cov.forecast_distinct_vintages >= 2


def test_rerun_is_idempotent(tmp_path, memory_db):
    transport = FakeTransport()
    transport._responder = _responder_factory(transport)
    client = ElexonClient(transport=transport, backoff=0.0, sleep=lambda _s: None)
    window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    pipeline.ingest_actuals(memory_db, client, window_start, window_end, data_dir=tmp_path)
    before = memory_db.execute("SELECT COUNT(*) FROM actuals").fetchone()[0]
    second = pipeline.ingest_actuals(
        memory_db, client, window_start, window_end, data_dir=tmp_path
    )
    after = memory_db.execute("SELECT COUNT(*) FROM actuals").fetchone()[0]
    assert before == after  # no new rows
    assert second.counts.inserted == 0
    assert second.counts.duplicates == before
