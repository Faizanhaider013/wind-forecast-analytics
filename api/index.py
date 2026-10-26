"""Vercel serverless entrypoint for the FastAPI backend.

Vercel's Python runtime serves the module-level ``app`` (an ASGI application).
``vercel.json`` routes every ``/api/*`` and ``/health`` request to this function;
all other paths are served as static files from the built frontend.

The backend lives in ``../backend`` as the ``app`` package, and the read-only
SQLite snapshot in ``../data/wind.db``. Both are bundled into the function via
``includeFiles`` in ``vercel.json``. No ingestion runs in this environment: the
API only ever READS the database (see backend/app/db.py), which suits Vercel's
read-only serverless filesystem perfectly.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Make the backend package importable (it lives alongside this file in ../backend).
sys.path.insert(0, str(ROOT / "backend"))

# Point the read-only DB loader at the bundled snapshot in ../data/wind.db.
os.environ.setdefault("WIND_DATA_DIR", str(ROOT / "data"))

# Served from the same Vercel origin as the frontend, so requests are
# same-origin and CORS is not involved. Leaving CORS_ORIGINS empty keeps the
# middleware from advertising any cross-origin access.
os.environ.setdefault("CORS_ORIGINS", "")

from app.main import app  # noqa: E402  (import must follow the sys.path setup above)

# Expose the ASGI app under the name Vercel's Python runtime looks for.
__all__ = ["app"]
