"""Ingestion orchestration: fetch -> cache -> normalise -> filter -> store.

The two public entry points are :func:`ingest_actuals` and
:func:`ingest_forecasts`, tied together by :func:`run`. Windowing respects the
API's 7-day limit; filtering is always on the record's TARGET delivery time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import cache, config, storage, timeutils
from .elexon_client import ElexonClient


# --- record normalisation ----------------------------------------------------


def normalize_actual(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise one FUELHH row. Raises ValueError on a structurally bad row."""
    start = row.get("startTime")
    if not start:
        raise ValueError("FUELHH row missing startTime")
    sp = row.get("settlementPeriod")
    if sp is None:
        raise ValueError("FUELHH row missing settlementPeriod")
    publish = row.get("publishTime")
    return {
        "target_start_time": timeutils.to_canonical_z(start),
        "settlement_date": timeutils.parse_settlement_date(
            row.get("settlementDate") or start
        ).isoformat(),
        "settlement_period": int(sp),
        "fuel_type": row.get("fuelType") or config.WIND_FUEL_TYPE,
        "generation_mw": row.get("generation"),
        "dataset": row.get("dataset") or "FUELHH",
        "publish_time": timeutils.to_canonical_z(publish) if publish else None,
    }


def normalize_forecast(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise one WINDFOR row. Raises ValueError on a structurally bad row."""
    start = row.get("startTime")
    publish = row.get("publishTime")
    if not start:
        raise ValueError("WINDFOR row missing startTime")
    if not publish:
        raise ValueError("WINDFOR row missing publishTime")
    return {
        "target_start_time": timeutils.to_canonical_z(start),
        "publish_time": timeutils.to_canonical_z(publish),
        "generation_mw": row.get("generation"),
        "dataset": row.get("dataset") or "WINDFOR",
    }


# --- windowing ---------------------------------------------------------------


def settlement_date_windows(
    start: date, end: date, max_days: int = config.MAX_WINDOW_DAYS
) -> list[tuple[str, str]]:
    """Inclusive ``YYYY-MM-DD`` windows of at most ``max_days`` calendar dates."""
    windows: list[tuple[str, str]] = []
    cursor = start
    step = timedelta(days=max_days - 1)  # inclusive span of max_days dates
    while cursor <= end:
        chunk_end = min(cursor + step, end)
        windows.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return windows


def publish_time_windows(
    start: datetime, end: datetime, max_days: int = config.MAX_WINDOW_DAYS
) -> list[tuple[str, str]]:
    """Inclusive ISO-8601 UTC publish windows of at most ``max_days`` each."""
    windows: list[tuple[str, str]] = []
    cursor = start
    span = timedelta(days=max_days)
    while cursor < end:
        chunk_end = min(cursor + span, end)
        windows.append(
            (timeutils.to_canonical_z(cursor), timeutils.to_canonical_z(chunk_end))
        )
        cursor = chunk_end
    return windows


# --- results -----------------------------------------------------------------


@dataclass
class StageResult:
    """Outcome of ingesting one dataset."""

    fetched: int = 0            # rows returned by the API (raw)
    kept: int = 0               # rows whose TARGET fell in the delivery window
    malformed: int = 0          # rows skipped because they were structurally bad
    counts: storage.UpsertCounts = field(default_factory=storage.UpsertCounts)
    cache_files: list[Path] = field(default_factory=list)


# --- ingestion stages --------------------------------------------------------


def ingest_actuals(
    conn,
    client: ElexonClient,
    window_start: datetime,
    window_end: datetime,
    *,
    data_dir: Path | None = None,
) -> StageResult:
    """Ingest FUELHH wind actuals whose target falls in ``[start, end)``."""
    result = StageResult()
    # FUELHH filters on settlement DATE; derive the inclusive date span from the
    # UTC target window (end is exclusive, so the last in-window day is end-1s).
    first_day = window_start.date()
    last_day = (window_end - timedelta(seconds=1)).date()

    for date_from, date_to in settlement_date_windows(first_day, last_day):
        print(f"  [actuals] FUELHH settlement {date_from}..{date_to}")
        rows = client.fetch_fuelhh_wind(date_from, date_to)
        result.fetched += len(rows)
        result.cache_files.append(
            cache.write_raw(
                "FUELHH", f"settlement_{date_from}_{date_to}", rows, data_dir=data_dir
            )
        )

        kept: list[dict[str, Any]] = []
        for row in rows:
            try:
                rec = normalize_actual(row)
            except (ValueError, TypeError) as exc:
                result.malformed += 1
                print(f"    ! skipping malformed FUELHH row: {exc}")
                continue
            if timeutils.in_target_window(
                rec["target_start_time"], window_start, window_end
            ):
                kept.append(rec)

        result.kept += len(kept)
        result.counts.add(storage.upsert_actuals(conn, kept))
        print(
            f"    fetched={len(rows)} kept={len(kept)} "
            f"inserted={result.counts.inserted} updated={result.counts.updated} "
            f"duplicates={result.counts.duplicates}"
        )
    return result


def ingest_forecasts(
    conn,
    client: ElexonClient,
    window_start: datetime,
    window_end: datetime,
    *,
    lookback_days: int = config.DEFAULT_FORECAST_LOOKBACK_DAYS,
    data_dir: Path | None = None,
) -> StageResult:
    """Ingest WINDFOR vintages whose TARGET falls in ``[start, end)``.

    WINDFOR has no target filter, so we request a publish window that starts
    ``lookback_days`` before the delivery window (to catch forecasts issued
    before the month that already cover its first days) and extends one day past
    it (to catch late-published vintages that still cover the final hours), then
    keep only rows whose target time is in-window.
    """
    result = StageResult()
    publish_start = window_start - timedelta(days=lookback_days)
    publish_end = window_end + timedelta(days=1)

    for pub_from, pub_to in publish_time_windows(publish_start, publish_end):
        print(f"  [forecasts] WINDFOR publish {pub_from}..{pub_to}")
        rows = client.fetch_windfor(pub_from, pub_to)
        result.fetched += len(rows)
        result.cache_files.append(
            cache.write_raw(
                "WINDFOR", f"publish_{pub_from}_{pub_to}", rows, data_dir=data_dir
            )
        )

        kept: list[dict[str, Any]] = []
        for row in rows:
            try:
                rec = normalize_forecast(row)
            except (ValueError, TypeError) as exc:
                result.malformed += 1
                print(f"    ! skipping malformed WINDFOR row: {exc}")
                continue
            if timeutils.in_target_window(
                rec["target_start_time"], window_start, window_end
            ):
                kept.append(rec)

        result.kept += len(kept)
        result.counts.add(storage.upsert_forecast_vintages(conn, kept))
        print(
            f"    fetched={len(rows)} kept_jan_targets={len(kept)} "
            f"inserted={result.counts.inserted} updated={result.counts.updated} "
            f"duplicates={result.counts.duplicates}"
        )
    return result


# --- top level ---------------------------------------------------------------


@dataclass
class RunResult:
    actuals: StageResult
    forecasts: StageResult
    coverage: storage.Coverage
    window_start: datetime
    window_end: datetime


def run(
    *,
    year: int = config.DEFAULT_TARGET_YEAR,
    month: int = config.DEFAULT_TARGET_MONTH,
    db_path: Path | None = None,
    data_dir: Path | None = None,
    lookback_days: int = config.DEFAULT_FORECAST_LOOKBACK_DAYS,
    client: ElexonClient | None = None,
    do_actuals: bool = True,
    do_forecasts: bool = True,
) -> RunResult:
    """Run a full ingestion for one target month and return a structured result."""
    db_path = db_path or config.default_db_path()
    client = client or ElexonClient()
    window_start, window_end = config.month_bounds_utc(year, month)

    print(
        f"Ingesting target month {year}-{month:02d} "
        f"[{timeutils.to_canonical_z(window_start)} .. "
        f"{timeutils.to_canonical_z(window_end)}) into {db_path}"
    )
    conn = storage.connect(db_path)
    try:
        actuals = (
            ingest_actuals(conn, client, window_start, window_end, data_dir=data_dir)
            if do_actuals
            else StageResult()
        )
        forecasts = (
            ingest_forecasts(
                conn,
                client,
                window_start,
                window_end,
                lookback_days=lookback_days,
                data_dir=data_dir,
            )
            if do_forecasts
            else StageResult()
        )
        coverage = storage.coverage_for_window(conn, window_start, window_end)
    finally:
        conn.close()

    return RunResult(
        actuals=actuals,
        forecasts=forecasts,
        coverage=coverage,
        window_start=window_start,
        window_end=window_end,
    )


def expected_actual_periods(window_start: datetime, window_end: datetime) -> int:
    """Expected number of half-hourly actual periods in the window (48/day)."""
    days = (window_end - window_start).days
    return days * 48


def expected_forecast_target_hours(window_start: datetime, window_end: datetime) -> int:
    """Expected number of distinct hourly forecast targets in the window."""
    return int((window_end - window_start).total_seconds() // 3600)
