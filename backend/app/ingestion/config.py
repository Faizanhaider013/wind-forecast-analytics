"""Static configuration and verified Elexon API facts for Phase 1 ingestion.

The constants here were verified against the live Elexon BMRS Insights API and
its OpenAPI definition (https://data.elexon.co.uk/swagger/v1/swagger.json) on
2026-10-25. See the README "Verified Elexon API facts" section.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

# --- Elexon BMRS Insights API ------------------------------------------------

# Public API; no API key is required.
BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"

# Dataset endpoints (relative to BASE_URL).
FUELHH_PATH = "/datasets/FUELHH"
WINDFOR_PATH = "/datasets/WINDFOR"

# The fuel type used to isolate wind actuals within FUELHH.
WIND_FUEL_TYPE = "WIND"

# Documented request limit: the inclusive date range of a single request must
# not exceed 7 days, for BOTH the FUELHH settlement-date window and the WINDFOR
# publish-time window. Verified: a >7-day window returns HTTP 400 with
# "The date range ... inclusive must not exceed 7 days".
MAX_WINDOW_DAYS = 7

# --- Target delivery period --------------------------------------------------

# Default target delivery month: January 2026 (UTC). Filtering is always done
# on the record's TARGET delivery timestamp, never on the API publication
# window. January is wholly within GMT (no British Summer Time), so UK
# settlement dates align with UTC calendar dates for this month.
DEFAULT_TARGET_YEAR = 2026
DEFAULT_TARGET_MONTH = 1

# Forecasts are published ahead of delivery, but WINDFOR offers no target-time
# filter -- only a publish-time window. Because a single WINDFOR publication
# covers a rolling horizon of roughly three days, forecasts published a few
# days BEFORE the delivery month still contain target times inside it. We
# therefore begin the forecast publish window this many days before the target
# month starts, then keep only rows whose TARGET time falls in the month.
DEFAULT_FORECAST_LOOKBACK_DAYS = 3

# --- HTTP behaviour ----------------------------------------------------------

HTTP_TIMEOUT_SECONDS = 60.0
HTTP_MAX_ATTEMPTS = 4
HTTP_BACKOFF_SECONDS = 2.0  # base for exponential backoff between retries
HTTP_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "uk-wind-forecast-tool/phase1 (+ingestion)"

# --- Local persistence -------------------------------------------------------


def default_data_dir() -> Path:
    """Resolve the project ``data/`` directory.

    Resolution order:
    1. ``WIND_DATA_DIR`` environment variable (used by Docker Compose, which
       mounts the host ``data/`` at ``/app/data``).
    2. The ``data/`` directory alongside the ``backend/`` directory (i.e. the
       repository root), computed relative to this file for local runs.
    """
    env = os.environ.get("WIND_DATA_DIR")
    if env:
        return Path(env)
    # .../backend/app/ingestion/config.py -> parents[2] == .../backend
    backend_dir = Path(__file__).resolve().parents[2]
    return backend_dir.parent / "data"


def default_db_path() -> Path:
    """Path to the SQLite database file inside the data directory."""
    return default_data_dir() / "wind.db"


def raw_cache_dir() -> Path:
    """Directory under ``data/`` where raw API JSON responses are cached."""
    return default_data_dir() / "raw"


def month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` UTC-aware bounds for the given calendar month.

    ``start`` is midnight on the first of the month; ``end`` is midnight on the
    first of the following month (exclusive).
    """
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end
