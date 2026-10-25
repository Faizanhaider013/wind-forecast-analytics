"""Raw API response caching under ``data/raw/<dataset>/``.

Every API response is written verbatim to disk before parsing, so a run can be
audited or replayed without re-hitting the API. Filenames encode the dataset
and the request window and are Windows-safe (no colons).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config


def _safe(token: str) -> str:
    """Make a timestamp/date token safe for a filename on any OS."""
    return token.replace(":", "").replace("+", "").replace(" ", "_")


def _dataset_dir(dataset: str, data_dir: Path | None = None) -> Path:
    base = (data_dir or config.default_data_dir()) / "raw" / dataset
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_raw(
    dataset: str,
    window_label: str,
    rows: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
) -> Path:
    """Write the raw rows for one request window to a JSON file; return its path.

    ``window_label`` describes the request window, e.g.
    ``settlement_2026-01-01_2026-01-07`` or
    ``publish_2025-12-29T000000Z_2026-01-05T000000Z``.
    """
    path = _dataset_dir(dataset, data_dir) / f"{_safe(window_label)}.json"
    path.write_text(
        json.dumps({"window": window_label, "data": rows}, indent=2),
        encoding="utf-8",
    )
    return path
