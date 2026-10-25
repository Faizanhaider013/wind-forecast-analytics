"""SQLite persistence for wind actuals and forecast vintages.

Uses the standard-library ``sqlite3`` module only. Idempotency is guaranteed by
UNIQUE constraints plus explicit upserts:

* ``actuals`` is keyed by (target_start_time, fuel_type). Re-ingesting replaces
  the stored value, so late-revised actuals converge to their final figure.
* ``forecast_vintages`` is keyed by (target_start_time, publish_time). Each
  distinct publication of a target time is a separate row, so a newer forecast
  NEVER overwrites an earlier vintage for the same target.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import timeutils

SCHEMA = """
CREATE TABLE IF NOT EXISTS actuals (
    target_start_time TEXT    NOT NULL,   -- UTC ISO 'YYYY-MM-DDTHH:MM:SSZ' (period start)
    settlement_date   TEXT    NOT NULL,   -- 'YYYY-MM-DD'
    settlement_period INTEGER NOT NULL,   -- 1..48/50
    fuel_type         TEXT    NOT NULL,   -- 'WIND'
    generation_mw     INTEGER,            -- actual generation, MW
    dataset           TEXT    NOT NULL,   -- source dataset, 'FUELHH'
    publish_time      TEXT,               -- source publication time (metadata)
    ingested_at       TEXT    NOT NULL,   -- when this row was written (UTC)
    UNIQUE (target_start_time, fuel_type)
);

CREATE INDEX IF NOT EXISTS idx_actuals_target ON actuals (target_start_time);

CREATE TABLE IF NOT EXISTS forecast_vintages (
    target_start_time TEXT    NOT NULL,   -- UTC ISO (hourly target)
    publish_time      TEXT    NOT NULL,   -- UTC ISO (the forecast vintage)
    generation_mw     INTEGER,            -- forecast generation, MW
    dataset           TEXT    NOT NULL,   -- source dataset, 'WINDFOR'
    ingested_at       TEXT    NOT NULL,   -- when this row was written (UTC)
    UNIQUE (target_start_time, publish_time)
);

CREATE INDEX IF NOT EXISTS idx_forecast_target  ON forecast_vintages (target_start_time);
CREATE INDEX IF NOT EXISTS idx_forecast_publish ON forecast_vintages (publish_time);
"""


@dataclass
class UpsertCounts:
    """Running tally of what an upsert batch did."""

    inserted: int = 0
    updated: int = 0
    duplicates: int = 0  # row already present with an identical value

    def add(self, other: "UpsertCounts") -> None:
        self.inserted += other.inserted
        self.updated += other.updated
        self.duplicates += other.duplicates

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.duplicates


def _now_z() -> str:
    return timeutils.to_canonical_z(datetime.now(timezone.utc))


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating parent dirs) and initialise the database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    return conn


# --- upserts -----------------------------------------------------------------


def upsert_actuals(
    conn: sqlite3.Connection, records: Iterable[dict], *, ingested_at: str | None = None
) -> UpsertCounts:
    """Insert or update wind actuals. Returns insert/update/duplicate counts.

    Each ``record`` must carry normalised keys: ``target_start_time``,
    ``settlement_date``, ``settlement_period``, ``fuel_type``,
    ``generation_mw``, ``dataset``, ``publish_time``.
    """
    ts = ingested_at or _now_z()
    counts = UpsertCounts()
    cur = conn.cursor()
    for rec in records:
        existing = cur.execute(
            "SELECT generation_mw FROM actuals "
            "WHERE target_start_time = ? AND fuel_type = ?",
            (rec["target_start_time"], rec["fuel_type"]),
        ).fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO actuals (target_start_time, settlement_date, "
                "settlement_period, fuel_type, generation_mw, dataset, "
                "publish_time, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec["target_start_time"],
                    rec["settlement_date"],
                    rec["settlement_period"],
                    rec["fuel_type"],
                    rec["generation_mw"],
                    rec["dataset"],
                    rec.get("publish_time"),
                    ts,
                ),
            )
            counts.inserted += 1
        elif existing["generation_mw"] == rec["generation_mw"]:
            counts.duplicates += 1
        else:
            cur.execute(
                "UPDATE actuals SET generation_mw = ?, settlement_date = ?, "
                "settlement_period = ?, dataset = ?, publish_time = ?, "
                "ingested_at = ? WHERE target_start_time = ? AND fuel_type = ?",
                (
                    rec["generation_mw"],
                    rec["settlement_date"],
                    rec["settlement_period"],
                    rec["dataset"],
                    rec.get("publish_time"),
                    ts,
                    rec["target_start_time"],
                    rec["fuel_type"],
                ),
            )
            counts.updated += 1
    conn.commit()
    return counts


def upsert_forecast_vintages(
    conn: sqlite3.Connection, records: Iterable[dict], *, ingested_at: str | None = None
) -> UpsertCounts:
    """Insert forecast vintages, preserving every distinct (target, publish).

    A conflict on (target_start_time, publish_time) means the same vintage was
    seen again: counted as a duplicate (identical value) or an update (value
    changed). Other vintages for the same target are never touched.
    """
    ts = ingested_at or _now_z()
    counts = UpsertCounts()
    cur = conn.cursor()
    for rec in records:
        existing = cur.execute(
            "SELECT generation_mw FROM forecast_vintages "
            "WHERE target_start_time = ? AND publish_time = ?",
            (rec["target_start_time"], rec["publish_time"]),
        ).fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO forecast_vintages (target_start_time, publish_time, "
                "generation_mw, dataset, ingested_at) VALUES (?, ?, ?, ?, ?)",
                (
                    rec["target_start_time"],
                    rec["publish_time"],
                    rec["generation_mw"],
                    rec["dataset"],
                    ts,
                ),
            )
            counts.inserted += 1
        elif existing["generation_mw"] == rec["generation_mw"]:
            counts.duplicates += 1
        else:
            cur.execute(
                "UPDATE forecast_vintages SET generation_mw = ?, dataset = ?, "
                "ingested_at = ? WHERE target_start_time = ? AND publish_time = ?",
                (
                    rec["generation_mw"],
                    rec["dataset"],
                    ts,
                    rec["target_start_time"],
                    rec["publish_time"],
                ),
            )
            counts.updated += 1
    conn.commit()
    return counts


# --- coverage reporting ------------------------------------------------------


@dataclass
class Coverage:
    """Summary of what the database holds for a target window."""

    actual_periods: int = 0
    actual_distinct_dates: int = 0
    actual_min_target: str | None = None
    actual_max_target: str | None = None
    forecast_rows: int = 0
    forecast_distinct_targets: int = 0
    forecast_distinct_vintages: int = 0
    forecast_min_target: str | None = None
    forecast_max_target: str | None = None
    missing_actual_dates: list[str] = field(default_factory=list)


def coverage_for_window(
    conn: sqlite3.Connection, window_start: datetime, window_end: datetime
) -> Coverage:
    """Compute coverage for actuals and forecasts whose TARGET is in-window."""
    start = timeutils.to_canonical_z(window_start)
    end = timeutils.to_canonical_z(window_end)
    cov = Coverage()
    cur = conn.cursor()

    row = cur.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT settlement_date) d, "
        "MIN(target_start_time) mn, MAX(target_start_time) mx FROM actuals "
        "WHERE target_start_time >= ? AND target_start_time < ?",
        (start, end),
    ).fetchone()
    cov.actual_periods = row["n"]
    cov.actual_distinct_dates = row["d"]
    cov.actual_min_target = row["mn"]
    cov.actual_max_target = row["mx"]

    row = cur.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT target_start_time) t, "
        "COUNT(DISTINCT publish_time) v, MIN(target_start_time) mn, "
        "MAX(target_start_time) mx FROM forecast_vintages "
        "WHERE target_start_time >= ? AND target_start_time < ?",
        (start, end),
    ).fetchone()
    cov.forecast_rows = row["n"]
    cov.forecast_distinct_targets = row["t"]
    cov.forecast_distinct_vintages = row["v"]
    cov.forecast_min_target = row["mn"]
    cov.forecast_max_target = row["mx"]

    return cov
