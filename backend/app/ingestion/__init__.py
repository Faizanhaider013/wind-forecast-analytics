"""Elexon ingestion package (Phase 1).

Fetches UK wind *actuals* (FUELHH, fuelType=WIND) and wind *forecasts*
(WINDFOR) from the Elexon BMRS Insights API and stores them in a local
SQLite database, preserving every distinct forecast vintage.

This package is intentionally independent of the FastAPI application: importing
or starting the API must never trigger a download. Run ingestion explicitly via
``python -m app.ingestion`` (see ``__main__``).
"""

from __future__ import annotations

__all__ = [
    "config",
    "timeutils",
    "elexon_client",
    "cache",
    "storage",
    "pipeline",
]
