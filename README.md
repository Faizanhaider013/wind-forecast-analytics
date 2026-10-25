# UK Wind Forecast Decision Tool

A decision-support tool for an energy utility, built around UK wind generation
data. **Phase 1 (Elexon ingestion into local SQLite) and Phase 2 (day-ahead
decision & forecast-accuracy APIs) are implemented.** Dashboards are not built
yet.

## Status

- [x] Project scaffold (monorepo, backend, frontend, tooling)
- [x] Elexon data ingestion — Phase 1 (actuals + forecast vintages → SQLite)
- [x] Decision & accuracy APIs — Phase 2 (`/api/*`, read-only over SQLite)
- [ ] Dashboard UI

> All data is **real** Elexon data. No fake or sample production data is
> generated. The frontend is unchanged and still only confirms it can reach the
> backend's health endpoint.

## Repository layout

```
.
├── backend/              # Python FastAPI application
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py       # FastAPI app + GET /health + CORS + /api router
│   │   ├── api.py        # Phase 2 /api routes (validation, HTTP errors)
│   │   ├── analytics.py  # Phase 2 decision/accuracy logic (pure, testable)
│   │   ├── db.py         # read-only SQLite access for the API
│   │   └── ingestion/    # Phase 1 Elexon ingestion package
│   │       ├── config.py        # verified API facts, paths, limits
│   │       ├── timeutils.py     # UTC parsing / canonicalisation / filtering
│   │       ├── elexon_client.py # stdlib HTTP client w/ retries & timeouts
│   │       ├── cache.py         # raw JSON response cache
│   │       ├── storage.py       # sqlite3 schema + idempotent upserts
│   │       ├── pipeline.py      # fetch → cache → filter → store orchestration
│   │       └── __main__.py      # CLI: `python -m app.ingestion`
│   ├── tests/            # offline pytest suite (HTTP + DB mocked)
│   ├── Dockerfile
│   ├── pytest.ini
│   ├── requirements.txt  # Python 3.13-compatible dependencies
│   └── .env.example
├── frontend/             # React + Vite + TypeScript application
│   ├── src/
│   │   ├── App.tsx       # App shell: header, nav, routes
│   │   ├── main.tsx      # Entry (BrowserRouter)
│   │   ├── index.css     # Design system (tokens, layout, components)
│   │   ├── api/          # Typed service layer (client, endpoints, types)
│   │   ├── hooks/        # useAsync (loading/error/data)
│   │   ├── components/   # Panel, StatCard, States, InfoTip
│   │   ├── pages/        # DecisionPage, AccuracyPage
│   │   ├── utils/        # MW/MWh/UK-time formatting
│   │   └── test/         # Vitest + Testing Library suite
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts    # Vite + Vitest config
│   ├── Dockerfile
│   └── .env.example
├── data/                 # Local data (generated contents are git-ignored)
├── docker-compose.yml    # Minimal local dev composition
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.13
- Node.js 20+ (developed against Node 22) and npm
- Docker (optional, only if using the Compose workflow)

## Local setup

The backend and frontend run as two separate processes. The commands below are
for **PowerShell on Windows**.

### 1. Backend

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Frontend

```powershell
cd frontend
npm install
```

## Running the app (two terminals)

**Terminal 1 — backend** (from the `backend/` directory, venv activated):

```powershell
uvicorn app.main:app --reload --port 8000
```

The API is then available at http://localhost:8000 and the health endpoint at
http://localhost:8000/health.

**Terminal 2 — frontend** (from the `frontend/` directory):

```powershell
npm run dev
```

Open http://localhost:5173. The app has two dashboards (see below). It needs the
ingested database, so run Phase 1 ingestion at least once before using it;
endpoints return HTTP 503 with guidance if `data/wind.db` is missing.

### Frontend dashboards (Phase 3)

A shared header switches between two pages:

- **Day-ahead decision** (`/decision`) — pick a delivery date (populated from
  `/api/available-dates`, defaulting to the first complete January 2026 date)
  and a day-ahead cutoff hour (default 10:00 UK). Plots the selected hourly
  forecast against the actual hourly-mean generation (MW, UK local time), with
  summary cards (avg forecast/actual MW, forecast/actual MWh), the selected
  forecast publication timestamps, a per-hour table, and a prominent coverage
  banner. Missing/unmatched hours show as gaps and are listed — never
  interpolated. Forecasts are the latest vintage published by the cutoff.
- **Forecast accuracy** (`/accuracy`) — fetches `/api/accuracy` for January 2026
  by default. Shows MAE, RMSE, bias, and WMAPE with explanatory tooltips
  (null-safe), the forecast-vs-persistence benchmark (only when the API marks it
  included), observation counts/coverage/exclusions, and an
  accuracy-by-horizon chart from `/api/accuracy/by-horizon` with sample counts.
  A toggle switches the horizon between *all vintages by lead time* and
  *day-ahead-eligible only*, clearly labelled so the two are not confused. The
  `/api/accuracy` response is aggregate (no per-day series), so a daily trend is
  intentionally not drawn rather than issuing one request per day.

The frontend never hardcodes data values; all numbers come from the API, and
missing values render as "—".

### Frontend checks

```powershell
cd frontend
npm run typecheck   # tsc -b
npm run test        # vitest (jsdom + Testing Library, fully offline)
npm run build       # tsc -b && vite build
```

### Configuration

- Backend CORS is configured to allow the Vite dev origin
  `http://localhost:5173`.
- The frontend reads `VITE_API_BASE_URL` (default `http://localhost:8000`).
  Copy `frontend/.env.example` to `frontend/.env` to override it.

## Running with Docker (optional)

```powershell
docker compose up --build
```

This builds and runs both services (backend on port 8000, frontend on port
5173) and has been verified end to end: the frontend dev server is served with
`--host`, the browser (on the host) reaches the backend at
`http://localhost:8000` via the `VITE_API_BASE_URL` set in Compose, and backend
CORS allows the `http://localhost:5173` origin.

The backend mounts the host `./data` directory, so the dashboards need the
database populated first. Run ingestion once (see Phase 1), then start the
stack:

```powershell
docker compose run --rm backend python -m app.ingestion --target-month 2026-01
docker compose up --build
```

## Phase 1 — Elexon data ingestion

Phase 1 downloads UK wind **actuals** and wind **forecasts** from the Elexon
BMRS Insights API and stores them in a local SQLite database, preserving every
distinct forecast vintage. It is completely separate from the FastAPI app —
starting the API never triggers a download.

### What it ingests

| Data        | Elexon dataset         | Resolution | Target filter used                      |
| ----------- | ---------------------- | ---------- | --------------------------------------- |
| Actuals     | `FUELHH`, `fuelType=WIND` | half-hourly | `settlementDateFrom`/`settlementDateTo` |
| Forecasts   | `WINDFOR`              | hourly     | publish window + **client-side target filter** |

### Verified Elexon API facts

Verified on 2026-10-25 against the live API and its OpenAPI definition
(`https://data.elexon.co.uk/swagger/v1/swagger.json`):

- **Base URL:** `https://data.elexon.co.uk/bmrs/api/v1` — public, **no API key**.
- **`GET /datasets/FUELHH`** accepts `settlementDateFrom`, `settlementDateTo`
  (`YYYY-MM-DD`), `fuelType`, `settlementPeriod`, and `format`. Returns
  `{"data": [ {dataset, publishTime, startTime, settlementDate,
  settlementPeriod, fuelType, generation}, … ]}` — 48 half-hourly rows/day.
  Supports **target-time filtering** by settlement date.
- **`GET /datasets/WINDFOR`** accepts **only** `publishDateTimeFrom`,
  `publishDateTimeTo` (ISO-8601 `…Z`) and `format` — **no target-time filter**.
  Returns `{"data": [ {dataset, publishTime, startTime, generation}, … ]}`,
  hourly. Each publication covers a rolling ~3-day horizon, and the feed
  re-publishes ~8× per day, so a target time has many vintages.
- **7-day limit:** a single request's inclusive date range must not exceed
  **7 days** for both datasets (a wider window returns HTTP 400). Requests are
  therefore chunked into ≤7-day windows.

> **Documented limitation (important):** WINDFOR cannot be filtered by target
> delivery time at the API, only by **publication** time. To cover January
> delivery dates we request forecasts published from a few days **before**
> 1 Jan 2026 (default 3) through just after month end, then keep only rows whose
> **target** `startTime` falls in January. Publication-time filtering is **not**
> the same as target-time filtering, and all records are validated and filtered
> on their target delivery timestamp.

### Storage (SQLite, stdlib `sqlite3`)

Database at `data/wind.db`, two tables:

- **`actuals`** — unique on `(target_start_time, fuel_type)`. Upserts replace the
  value, so revised actuals converge to their final figure.
- **`forecast_vintages`** — unique on `(target_start_time, publish_time)`. Each
  publication is a separate row; a newer forecast **never overwrites** an earlier
  vintage for the same target. Ingestion is idempotent — re-running inserts
  nothing new and reports duplicates.

Raw API responses are cached verbatim under `data/raw/<dataset>/` (one file per
request window). The whole `data/` directory is git-ignored.

### Running ingestion

**Via Docker Compose (recommended — no need to enter the container):**

```powershell
# Build once so the backend image has the ingestion code:
docker compose build backend

# Ingest January 2026 (default target month); writes to ./data on the host:
docker compose run --rm backend python -m app.ingestion --target-month 2026-01
```

**Locally** (from `backend/`, venv activated):

```powershell
python -m app.ingestion --target-month 2026-01
```

Useful flags: `--actuals-only`, `--forecasts-only`,
`--forecast-lookback-days N`, `--db-path PATH`, `--data-dir PATH`.

### Expected output

Progress is printed per request window, followed by a summary. A verified full
January 2026 run reports:

```
Actuals (FUELHH, fuelType=WIND):
  Coverage                  : 1488/1488 half-hourly periods across 31/31 dates
  Target range              : 2026-01-01T00:00:00Z .. 2026-01-31T23:30:00Z

Forecast vintages (WINDFOR):
  Coverage                  : 744/744 hourly target times; 272 distinct vintages; 18104 rows
  Target range              : 2026-01-01T00:00:00Z .. 2026-01-31T23:00:00Z

Coverage verdict:
  Actuals   : COMPLETE
  Forecasts : COMPLETE
```

The summary always reports records fetched, inserted, updated, duplicates, and
date coverage, and only prints `COMPLETE` when the stored counts actually meet
the expected period/hour counts for the month.

### Tests

The test suite is fully offline (HTTP is mocked through an injectable
transport) and covers timestamp parsing, January target filtering, request
windowing, deduplication/idempotency, forecast-vintage retention, and
half-hourly vs hourly granularity.

```powershell
# Docker:
docker compose run --rm backend pytest

# Local (from backend/):
pytest
```

## Phase 2 — Decision & accuracy API

Phase 2 adds read-only HTTP endpoints over the ingested database. They never
write to the database and never trigger ingestion; if `data/wind.db` is absent
they return `503` telling you to run ingestion first. Start the backend as usual
(`uvicorn app.main:app --port 8000`, or `docker compose up backend`) and the
endpoints are served under `/api`. Interactive docs are at
`http://localhost:8000/docs`.

### Conventions (read this before trusting a number)

- **Signed error = forecast − actual (MW).** A positive error / bias means the
  forecast **over**predicts.
- **Granularity is never faked.** Forecasts (WINDFOR) are hourly; actuals
  (FUELHH) are half-hourly. An hourly actual is the **mean of the two**
  half-hourly observations in that hour. An hour with fewer than two present
  observations is reported **incomplete** and is never imputed or matched.
- **Day-ahead cutoff.** The default cutoff is **10:00 Europe/London on the day
  before delivery**, configurable via `cutoff_hour`. It is interpreted in London
  local time (DST-aware via `zoneinfo`) and converted to UTC before comparing
  with forecast `publishTime`. For each hourly target the **latest forecast
  vintage published at or before the cutoff** is selected; a forecast published
  after the cutoff is never used.
- **Units:** power in MW; energy in MWh. Each hourly mean-MW value spans one
  hour, so summing hourly MW gives MWh.
- All timestamps are UTC (`…Z`); cutoff objects also report the London local
  time for auditing.

### Endpoints

#### `GET /api/available-dates`

Per-date coverage so the frontend can distinguish complete from partial dates.
Each date reports actual half-hour periods (of 48 expected), forecast target
hours (of 24) and vintage count, with `complete` flags.

#### `GET /api/decision/{delivery_date}?cutoff_hour=10`

Day-ahead hourly forecast-vs-actual for one UK delivery day. Returns, per hour:
`hour_utc`, `forecast_mw`, **`forecast_publish_time`** (so the vintage selection
is auditable), `actual_mean_mw` (null if the hour is incomplete),
`actual_n_half_hours`, `error_mw`, and a `matched` flag. The `summary` gives
average forecast/actual MW and total MWh over the day (hourly-mean basis, plus a
native half-hourly energy total), and `coverage` lists missing-forecast and
incomplete-actual hours. `400` on a malformed date; `422` on a `cutoff_hour`
outside 0–23.

#### `GET /api/accuracy?from=2026-01-01&to=2026-01-31&cutoff_hour=10`

Accuracy metrics over a date range using the same day-ahead selection
(defaults to January 2026). Metrics are computed **only** over hours with both
an eligible forecast and a complete hourly actual; excluded hours are counted.

- `mae_mw`, `rmse_mw`
- `bias_mw` (positive = forecasts overpredict)
- `wmape_fraction` / `wmape_percent` — WMAPE = Σ|forecast−actual| / Σ(actual).
  Actual wind generation is non-negative, so the denominator is Σ(actual); when
  it is zero WMAPE is returned as `null` with an explanatory note.
- `n` matched observations and `coverage` (expected vs matched hours, exclusions).
- **`persistence_benchmark`** — a naive baseline: the forecast for delivery hour
  *h* is the actual hourly mean at the **same hour two days earlier** (the most
  recent fully-observed day at a previous-day cutoff, so it never uses future
  information). Reported only where that prior actual exists (e.g. the first two
  days of the ingested month are excluded); `included: false` with a reason
  otherwise. The skill comparison is **paired**: `skill_mae_percent`,
  `model_mae_mw_same_sample`, and `model_rmse_mw_same_sample` restrict the
  forecast's own error to exactly the hours the benchmark covers, so the two are
  scored on one sample rather than dividing the model's whole-range MAE by the
  benchmark's smaller-sample MAE. On the ingested January data the day-ahead
  forecast (MAE ≈ 2012 MW on the common 696 hours) clearly beats persistence
  (MAE ≈ 4184 MW) — a skill of ≈ 52%.

#### `GET /api/accuracy/by-horizon?from=2026-01-01&to=2026-01-31`

Forecast error grouped by **lead time = target − publishTime**, in documented
half-open buckets (`<0h`, `0-6h`, `6-12h`, `12-18h`, `18-24h`, `24-36h`,
`36-48h`, `48h+`), each with `n`, `mae_mw`, `rmse_mw`, `bias_mw`. The `<0h`
bucket holds vintages published at or after their target (WINDFOR re-publishes
recent hours).

> This endpoint deliberately uses **all** stored vintages grouped by their own
> lead time — it is **not** the single day-ahead selection, and is labelled as
> such so it is not mistaken for day-ahead horizon accuracy. An optional
> `cutoff_hour` restricts it to vintages available at each target's day-ahead
> cutoff (never future vintages); omit it for the full horizon curve.

### Tests

The Phase 2 tests are fully offline (in-memory SQLite; the HTTP layer via
FastAPI's `TestClient`) and cover cutoff computation, UK DST transitions
(23/24/25-hour days), latest-eligible-vintage selection and cutoff enforcement,
half-hourly→hourly aggregation and missing-data handling, metric calculations,
WMAPE zero-denominator safety, horizon bucketing, and API validation/errors. Run
them the same way as Phase 1:

```powershell
docker compose run --rm backend pytest    # or, locally from backend/: pytest
```

## Deployment

Deployment links will be added here once the application is deployed.

- Frontend: _TBD_
- Backend: _TBD_

### Production notes

- **CORS:** set `CORS_ORIGINS` on the backend to the deployed frontend
  origin(s), comma-separated (see `backend/.env.example`). It defaults to the
  Vite dev origin, which will block a production browser frontend.
- **Frontend API URL:** `VITE_API_BASE_URL` is inlined at **build time** by
  Vite, so it must be set when running `npm run build` for production (not just
  at runtime).
- **Docker images are development-oriented:** the frontend image runs the Vite
  dev server (`npm run dev --host`), not a production static build. For
  production, build the static bundle (`npm run build`) and serve `dist/` from a
  static host or add a multi-stage image (build + nginx). The backend image runs
  uvicorn directly without `--reload`, which is acceptable for a single-worker
  deployment; put it behind a process manager / reverse proxy for production.
- **Database persistence:** the backend reads `data/wind.db` (mounted via
  Compose at `/app/data`). Ingestion must be run to populate it before the API
  can serve data; the API is read-only and returns `503` if the database is
  missing.

## AI tools disclosure

This project was scaffolded with the assistance of AI tooling (Anthropic's
Claude, via Claude Code). AI was used to generate the initial project
structure, configuration files, and boilerplate. All generated code has been
reviewed and is the responsibility of the author.
