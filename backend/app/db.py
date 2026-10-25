"""Read-only SQLite access for the Phase 2 analytics API.

The API only ever reads the database that Phase 1 ingestion produced. Opening in
read-only URI mode guarantees the API can never create, migrate, or mutate the
database, and fails fast with a clear message if ingestion has not run yet.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .ingestion import config


class DatabaseUnavailable(RuntimeError):
    """Raised when the SQLite database does not exist or cannot be opened."""


def get_db_path() -> Path:
    """Path to the ingestion database (``data/wind.db`` by default)."""
    return config.default_db_path()


def connect_readonly(path: Path | None = None) -> sqlite3.Connection:
    """Open the database read-only. Raises DatabaseUnavailable if missing."""
    db_path = path or get_db_path()
    if not db_path.exists():
        raise DatabaseUnavailable(
            f"database not found at {db_path}. Run ingestion first, e.g. "
            f"`python -m app.ingestion --target-month 2026-01`."
        )
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:  # pragma: no cover - defensive
        raise DatabaseUnavailable(f"cannot open {db_path} read-only: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn
