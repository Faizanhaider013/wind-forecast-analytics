"""UTC-aware timestamp parsing, canonicalisation, and target-window filtering.

All timestamps are handled as timezone-aware UTC ``datetime`` objects and
serialised to a single canonical string form (``YYYY-MM-DDTHH:MM:SSZ``) so that
equality and uniqueness in SQLite are well-defined regardless of the exact
spelling the API used (``Z`` vs ``+00:00``, fractional seconds, etc.).
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC ``datetime``.

    Accepts a trailing ``Z`` (Zulu) or an explicit offset. A timestamp without
    any timezone designator is rejected, because silently assuming a zone is
    exactly the kind of ambiguity this project must avoid.

    Raises:
        ValueError: if ``value`` is empty, not a timestamp, or has no timezone.
    """
    if value is None:
        raise ValueError("timestamp is None")
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")

    # datetime.fromisoformat understands "+00:00" offsets and (3.11+) a "Z"
    # suffix, but we normalise "Z" ourselves for compatibility and clarity.
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp: {value!r}") from exc

    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no timezone offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def to_canonical_z(value: str | datetime) -> str:
    """Return the canonical ``YYYY-MM-DDTHH:MM:SSZ`` form of a timestamp.

    Fractional seconds are dropped to the whole second; Elexon settlement and
    publication timestamps are whole-second aligned.
    """
    dt = value if isinstance(value, datetime) else parse_utc(value)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_settlement_date(value: str) -> date:
    """Parse an Elexon settlement date (``YYYY-MM-DD``) into a ``date``."""
    text = (value or "").strip()
    if not text:
        raise ValueError("empty settlement date")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"unparseable settlement date: {value!r}") from exc


def in_target_window(
    target_start: str | datetime,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    """True if ``target_start`` lies in ``[window_start, window_end)`` (UTC).

    ``window_end`` is exclusive, so the half-open month window correctly keeps
    the final delivery period of the month and excludes the first period of the
    next month.
    """
    dt = target_start if isinstance(target_start, datetime) else parse_utc(target_start)
    dt = dt.astimezone(timezone.utc)
    return window_start <= dt < window_end
