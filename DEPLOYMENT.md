# Deployment

This is the production runbook for Atlas. It covers the recommended hosting stack, the full
environment-variable checklist, the database migration/release step, and data durability. Account
and secret provisioning (creating the Neon project, the API keys, the host accounts) is a manual
step; this document gets the repository ready for it.

## Architecture recap

Three deployable pieces:

- **Backend**: FastAPI app (`api.main:app`), served by uvicorn. Streams chat over Server-Sent
  Events, so it needs a long-lived process, not a serverless function.
- **Database**: PostgreSQL with the `pgvector` extension (the `semantic_cache` table stores
  embeddings in a `vector` column).
- **Frontend**: static React build (`frontend/`), output of `npm run build`.

## Recommended stack

| Piece    | Recommendation                          | Why |
|----------|-----------------------------------------|-----|
| Database | **Neon** Postgres                       | pgvector is available built-in; serverless Postgres with automated backups. Connect with `sslmode=require`. |
| Backend  | **Railway** or **Render** (container)   | Runs the Docker image as a persistent process, which SSE needs. Both inject `$PORT` (the Dockerfile honors it). |
| Frontend | **Vercel** or **Cloudflare Pages**      | Cheap, fast static hosting/CDN for the built assets. |

**Do not put the SSE backend on Vercel serverless** (or any serverless/edge function platform).
The `/api/chat/stream` endpoint holds an open streaming response for the duration of a planning run;
serverless functions buffer responses and enforce short execution limits, which breaks streaming and
will time out long plans. The static frontend on Vercel is fine; the backend is not.

## Environment variables

### Backend

| Variable            | Required | Notes |
|---------------------|----------|-------|
| `OPENAI_API_KEY`    | yes      | Primary LLM + embeddings provider. The only LLM key required while `USE_GEMINI=False` (the current default in `core/llm.py`). |
| `GEMINI_API_KEY`    | if hybrid | Fallback LLM provider for research/extraction/critic. Needed only when `USE_GEMINI=True`; unused in the current OpenAI-only mode. |
| `ENVIRONMENT`       | yes      | Set to `production`. This makes the app refuse to start unless `JWT_SECRET_KEY` is a real value, so a host can't accidentally boot with the forgeable default. Defaults to `development`. |
| `JWT_SECRET_KEY`    | yes      | Real secret in production. Generate: `python -c "import secrets; print(secrets.token_hex(32))"`. Do not ship the `change-this-in-production` placeholder; with `ENVIRONMENT=production` the app will not start if you do. |
| `JWT_EXPIRE_MINUTES`| no       | Token lifetime; defaults to 1440 (24h). |
| `DATABASE_URL`      | yes      | `postgresql://user:pass@host:port/db`. For Neon append `?sslmode=require`. |
| `CORS_ORIGINS`      | yes      | Comma-separated allowed frontend origins, e.g. `https://atlas.example.com`. Must include the deployed frontend domain or the browser blocks API calls. |
| `API_KEY`           | no       | If set, callers must send `X-API-Key`. Leave empty to disable (the JWT user auth is independent of this). |
| `RATE_LIMIT_MAX`    | no       | Max requests per IP per window. Default 30. |
| `RATE_LIMIT_WINDOW` | no       | Window in seconds. Default 60. |

### Frontend

| Variable        | Required | Notes |
|-----------------|----------|-------|
| `VITE_API_URL`  | yes (prod) | Backend origin, no trailing slash and no `/api` suffix, e.g. `https://atlas-api.up.railway.app`. **Baked in at build time** by Vite, so it must be set in the build environment, not at runtime. Leave empty for local dev (the Vite proxy handles it). |

See `.env.example` (backend, repo root) and `frontend/.env.example`.

## Database migrations / release step

**Alembic is the source of truth for the schema.** Migrations live in `migrations/versions/`; the
baseline (`29823c6a0cd9`) runs `CREATE EXTENSION IF NOT EXISTS vector` before creating the tables, so
a clean managed Postgres is provisioned correctly. There is no `create_all()` path anymore.

On startup, the app's lifespan handler calls `init_db()`, which runs `alembic upgrade head` and is
idempotent (a no-op when already at head). For a **single backend instance** this means deploys
self-migrate with no extra step.

For **multiple replicas**, several instances racing `upgrade head` on boot is undesirable. Run the
migration once as an explicit release step instead:

```bash
alembic upgrade head
```

On Render, set this as the **Pre-Deploy Command**; on Railway, as a release/deploy command. If you
adopt this, you can drop the on-startup migration (the `_run_migrations()` call in
`core/database.py::init_db()`) so boot does not touch the schema. Until you scale past one instance,
the on-startup migration is the simpler default and is fine to keep.

## Health checks

- `GET /` is a cheap liveness probe.
- `GET /health` is a deep check: it runs `SELECT 1` and returns 503 if the database is unreachable.
  Point the host's health check at `/health` so an instance that lost its DB is taken out of
  rotation.

Both paths are exempt from the rate limiter.

## Production data durability

- **Backups.** Enable automated backups on the managed Postgres and set a retention window
  (Neon provides point-in-time restore; pick a retention period that matches your recovery needs).
  All durable state (users, saved trips, shared itineraries, the semantic/geocoding caches) lives in
  Postgres, so the database backup is the whole backup.
- **Safe migrations.** Treat migrations as expand/contract: add columns/tables in one release, move
  reads/writes over, drop old columns only in a later release once nothing references them. Avoid
  destructive `downgrade`-style changes against production data. Test each migration against a copy
  of production before release.
- **Per-instance state does not scale to replicas (yet).** The rate limiter and the metrics counters
  in `api/main.py` are plain in-process dicts (`_rate_limit_store`, `_metrics`). With more than one
  replica each instance counts only its own traffic, so limits are effectively multiplied by the
  replica count and `/api/metrics` reports per-instance numbers. Before scaling out, move the rate
  limiter to a shared store (e.g. Redis) and export metrics to an external collector. For a single
  instance this is not a problem.

## Local production-like run

`docker-compose.yml` brings up Postgres (the `pgvector/pgvector:pg16` image), the backend, and the
frontend together. Copy `.env.example` to `.env` and fill in the keys first. To bake the API URL
into the frontend image, pass the build arg, e.g.:

```yaml
  frontend:
    build:
      context: ./frontend
      args:
        VITE_API_URL: ""   # empty is fine in compose; the backend is reachable on the same host
```
