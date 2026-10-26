# Deploying to Vercel

This project is configured to deploy as a **single Vercel project** that serves
both the React frontend and the FastAPI backend on one origin:

- **Frontend** — the Vite build (`frontend/`) is served as static files.
- **Backend** — FastAPI runs as a Python serverless function (`api/index.py`).
  `vercel.json` routes `/api/*` and `/health` to it; everything else falls back
  to the SPA (`index.html`).
- **Data** — the API reads a bundled, read-only snapshot at `data/wind.db`
  (`actuals` + `forecast_vintages`). No ingestion runs on Vercel.

> **This is a snapshot deployment.** Vercel's serverless filesystem is
> read-only, so the data does not refresh itself. To update the figures the
> client sees, re-run ingestion locally and redeploy (see "Refreshing the data").

## Option A — Deploy from Git (recommended)

1. Push the repo to GitHub/GitLab/Bitbucket. `data/wind.db` is intentionally
   committed (the `.gitignore` files un-ignore it) so the function has data.
2. In the Vercel dashboard: **Add New → Project → Import** your repo.
3. Leave **Root Directory** as the repo root. `vercel.json` does the rest —
   do not set a framework preset or override the build command.
4. Click **Deploy**. The URL Vercel gives you is what you show the client.

## Option B — Deploy from your machine with the CLI

```bash
npm i -g vercel
cd "UK wind prediction"
vercel          # first run: links/creates the project, then deploys a preview
vercel --prod   # promote to the production URL for the client
```

The CLI uploads local files (respecting `.vercelignore`), so `data/wind.db` is
included even if you haven't committed it.

## Verifying a deployment

- `https://<your-app>.vercel.app/` — the dashboard loads.
- `https://<your-app>.vercel.app/health` — returns `{"status":"ok"}`.
- `https://<your-app>.vercel.app/api/available-dates` — returns JSON.

## Refreshing the data

```bash
cd backend
python -m app.ingestion --target-month 2026-01   # rewrites ../data/wind.db
```

Then redeploy (push to Git, or `vercel --prod`).

## How the pieces fit

| File | Purpose |
|------|---------|
| `vercel.json` | Builds the frontend + Python function; routes `/api` & `/health` to the API, SPA fallback for the rest. |
| `api/index.py` | Serverless entrypoint; puts `backend/` on the path and points the read-only DB loader at `data/wind.db`. |
| `api/requirements.txt` | Runtime deps for the function (FastAPI + tzdata only). |
| `.vercelignore` | Keeps CLI uploads small; **does not** exclude `data/wind.db`. |

The Docker setup (`docker-compose.prod.yml`) is unchanged and still works for a
container host — Vercel is an additional, self-contained target.
