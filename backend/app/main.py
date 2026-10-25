"""UK Wind Forecast Decision Tool - backend API.

Exposes the health check plus the Phase 2 decision and accuracy endpoints
(``/api/*``). These endpoints only READ the SQLite database produced by Phase 1
ingestion; ingestion is never triggered from application startup -- it is run
explicitly via ``python -m app.ingestion``.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router as api_router

# Default to the local Vite dev origin; override in production by setting
# CORS_ORIGINS to a comma-separated list of allowed origins (documented in
# backend/.env.example). The browser frontend's origin must appear here.
DEFAULT_CORS_ORIGINS = "http://localhost:5173"


def cors_origins(env_value: str | None) -> list[str]:
    """Parse the CORS_ORIGINS env value into a clean list of origins."""
    raw = env_value if env_value is not None else DEFAULT_CORS_ORIGINS
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(
    title="UK Wind Forecast Decision Tool API",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(os.environ.get("CORS_ORIGINS")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend and by deployment checks."""
    return {"status": "ok"}


# Phase 2 decision/accuracy API (read-only over the ingested database).
app.include_router(api_router)
