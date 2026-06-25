# Atlas Travel Companion

Atlas turns a short conversation into a structured, day-by-day travel itinerary. A user describes
the trip in plain language; a multi-agent LangGraph pipeline interviews them for the missing
details, researches food, activities, and lodging, optimizes the route, writes the plan, and reviews
its own output. The web app shows the chat and the resulting itinerary side by side, with an
interactive map of each day's stops.

It is a non-commercial learning project, built to practice agent orchestration, streaming, and
full-stack product engineering.

## What it does

- **Conversational planning with a deterministic interview gate.** The interviewer extracts what is
  known each turn and decides *in code* whether enough is known to plan (destination and duration are
  required) or which single question to ask next. This slot-filling gate, not the LLM's memory, is
  what stops the interview from looping or re-asking answered questions.
- **Split chat + itinerary canvas.** Once a plan exists the view splits: the conversation stays on
  one side, the rendered itinerary on the other. On mobile the split collapses to a chat/itinerary
  toggle.
- **Interactive map.** A Leaflet map pins each day's stops, colored by day, with route lines and the
  hotel marked.
- **Streaming responses.** Chat is delivered token-by-token over Server-Sent Events, with live status
  updates as the pipeline moves through its stages.
- **Accounts and persistence.** JWT auth with email verification, password reset, and account
  deletion. Saved trips, saved chat sessions, and saved travel preferences.
- **Saved, shared, and collaborative trips.** Trips persist to a sidebar; a trip can be shared
  read-only via an unguessable public link, or shared with another registered user as a viewer or
  editor (collaboration is keyed on trip membership).
- **A/B variants and regenerate.** A plan can be requested in compare mode, which streams two
  diversified variants for the user to choose between; the chosen one is committed. A delivered plan
  can also be regenerated from scratch with fresh ideas.
- **Export and sharing.** One-click PDF export (rendered server-side), a public share link, and a
  full personal-data export.
- **Personalization.** Saved profile preferences seed the interview so Atlas stops re-asking. An
  implicit-signal layer records behavioral signals (a plan kept, regenerated, or edited; a variant
  kept; a trip opened) and folds them, plus explicit star ratings, into an advisory preference
  "portrait" that steers later plans. Scoring is heuristic, not an ML model.
- **Product analytics.** Optional PostHog funnel analytics, behind a consent gate and a write-key
  gate; a hard no-op unless both open.
- **Privacy controls.** A consent banner, a personal-data export endpoint, and account deletion that
  cascades the user's trips, sessions, preferences, and tokens.
- **Semantic cache.** Research results are cached as pgvector embeddings and reused when a new query
  is similar enough and fresh enough, to cut latency and API cost.
- **Multi-destination trips.** A single request can cover more than one city.

## Architecture at a glance

```
Browser (React 19 + Vite)
  │  POST /api/chat/stream   (Server-Sent Events)
  ▼
FastAPI (api/main.py, api/chat.py)
  │  TravelOrchestrator.stream_chat  (core/orchestrator.py)
  ▼
LangGraph StateGraph (core/graph.py, core/nodes/)
  Interviewer ──(gate: enough info?)──► Research (food ‖ activity ‖ hotel)
        │                                      │  each checks the pgvector semantic cache first
        │                                      ▼
        └─ ask one question / answer       Logistics (async geocoding + zone routing)
                                               ▼
                                           Compiler (writes the itinerary, emits map geo)
                                               ▼
                                           Critic (quality review; may loop back)
  │
  ▼
PostgreSQL + pgvector  (users, trips, chat_sessions, preferences, signals, cache, …)
```

More detail, with diagrams, lives in [docs/](docs/).

## Tech stack

| Component | Technology |
|---|---|
| Frontend | React 19, Vite, react-leaflet / Leaflet, Framer Motion, react-markdown + remark-gfm, posthog-js |
| Backend | FastAPI, Pydantic v2, Uvicorn |
| Agent framework | LangGraph, LangChain |
| LLMs | OpenAI GPT-4o-mini (primary). Google Gemini 2.5 Flash / Flash Lite is a flag-gated fallback for the research, extraction, and critic roles (see note below) |
| Embeddings | OpenAI text-embedding-3-small |
| Database | PostgreSQL 16 + pgvector |
| Migrations | Alembic |
| Auth | JWT (python-jose), bcrypt |
| Geocoding | Geopy (Nominatim), run in a worker thread, cached in Postgres |
| PDF export | Playwright (server-side HTML-to-PDF) |
| Containerization | Docker, docker-compose |
| CI | GitHub Actions |

### A note on the LLM strategy

The code assigns each pipeline role a best-fit model in [`core/llm.py`](core/llm.py). The design is
hybrid: OpenAI for the conversational and writing roles (interviewer, compiler) and Gemini for
research, extraction, and critic, because Gemini's Google Search grounding returns live data.

That hybrid path is gated behind a `USE_GEMINI` flag, **currently set to `False`**, so every role
runs on OpenAI right now (the Gemini prepay quota was depleted). In OpenAI-only mode the research
nodes run **without** Google Search grounding, so their place data comes from the model rather than a
live search. Flipping `USE_GEMINI` back to `True` (with Gemini billing in place) restores the hybrid
setup and live grounding. Because of this, `OPENAI_API_KEY` is the only LLM key strictly required to
run the app today; `GEMINI_API_KEY` is needed only when the hybrid mode is enabled.

## Running locally

### Option 1: Docker (recommended)

Brings up Postgres (the `pgvector/pgvector:pg16` image), the backend, and the frontend together.

```bash
cp .env.example .env
# Edit .env: set OPENAI_API_KEY at minimum.

docker compose up --build
```

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000` (docs at `/docs`)

### Option 2: Local backend

Prerequisites: Python 3.12+, PostgreSQL 16+ with the `pgvector` extension.

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: set OPENAI_API_KEY and DATABASE_URL.

python run_api.py               # starts the FastAPI app on :8000
```

The app runs Alembic migrations to head on startup (idempotent), so the schema is created and the
`pgvector` extension is enabled for you.

### Option 3: Local frontend

```bash
cd frontend
npm install
npm run dev                     # Vite dev server on :5173
```

The Vite dev server proxies `/api` and `/health` to `http://localhost:8000`, so run the backend
alongside it.

### Option 4: CLI

```bash
python cli.py                   # Rich terminal interface to the same pipeline
```

## Configuration

Configuration is via environment variables; see [`.env.example`](.env.example) (backend) and
[`frontend/.env.example`](frontend/.env.example).

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | - | OpenAI key (interviewer, compiler, embeddings, and all roles while `USE_GEMINI=False`) |
| `GEMINI_API_KEY` | Only if hybrid enabled | - | Google Gemini key; used only when `USE_GEMINI=True` |
| `DATABASE_URL` | Yes | `postgresql://postgres:postgres@localhost:5432/travel_companion` | PostgreSQL connection string |
| `ENVIRONMENT` | Prod | `development` | Set to `production` to make the app refuse to start with a missing/default `JWT_SECRET_KEY` |
| `JWT_SECRET_KEY` | Prod | `change-this-in-production` | Secret for signing JWTs; must be a real value in production |
| `JWT_EXPIRE_MINUTES` | No | `1440` | Access-token lifetime in minutes |
| `API_KEY` | No | - | Optional admin key via `X-API-Key`; empty disables it |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:5173` | Allowed frontend origins (no wildcards) |
| `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW` | No | `30` / `60` | Per-IP sliding-window rate limit |
| `RESEND_API_KEY`, `EMAIL_*` | No | - | Transactional email for verification/reset; degrades to a logged no-op when unset |
| `VITE_API_URL` (frontend) | Prod | - | Backend origin, baked in at build time; leave empty for local dev |
| `VITE_POSTHOG_KEY` (frontend) | No | - | PostHog write key; analytics stay off until this and consent are both present |

## API surface

All routes are under `/api` unless noted. Auth is a Bearer JWT; many chat routes also work
anonymously.

**Chat** (`api/chat.py`)
- `POST /api/chat` - non-streaming chat
- `POST /api/chat/stream` - SSE streaming chat (the web UI uses this)
- `POST /api/chat/keep-variant` - commit the chosen A/B variant

**Auth, account, preferences, trips, sessions** (`api/users.py`)
- `POST /api/users/register`, `POST /api/users/login`
- `GET /api/users/me`, `POST /api/users/me/password`, `DELETE /api/users/me`
- `POST /api/users/verify-email`, `POST /api/users/resend-verification`
- `POST /api/users/forgot-password`, `POST /api/users/reset-password`
- `GET /api/users/me/export` - personal-data export
- `GET/PUT /api/users/preferences`
- `GET /api/users/trips`, `GET /api/users/trips/shared`, `GET /api/users/trips/{id}`, `DELETE /api/users/trips/{id}`
- `GET /api/users/trips/{id}/members`, `POST /api/users/trips/{id}/members`, `DELETE /api/users/trips/{id}/members/{user_id}`
- `GET /api/users/sessions`, `GET /api/users/sessions/{id}`, `DELETE /api/users/sessions/{id}`

**Export, share, feedback, signals**
- `POST /api/export/pdf` (`api/export.py`)
- `POST /api/share`, `GET /api/share/{id}`, `DELETE /api/share/{id}` (`api/share.py`)
- `POST /api/feedback` (`api/feedback.py`)
- `POST /api/signals` - client-reported `trip_opened` only (`api/signals.py`)

**Health, cache, observability** (`api/main.py`)
- `GET /` (liveness), `GET /health` (deep DB check)
- `GET /api/cache/stats`, `GET /api/cache/inspect/{destination}`, `GET /api/cache/test-similarity`
- `POST /api/cache/clear-stale`, `POST /api/users/prune-tokens` (API-key gated)
- `GET /api/metrics`, `GET /api/debug/logs` (API-key gated)

Every response carries `X-Request-ID` and `X-Response-Time-Ms` headers.

### Example

```bash
# Anonymous, non-streaming
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Plan a 3-day trip to Paris on a medium budget"}'
```

## Project structure

```
travel-companion/
├── api/
│   ├── main.py          # FastAPI app, middleware, cache/metrics/health endpoints
│   ├── chat.py          # chat + SSE streaming + keep-variant (DB-persisted)
│   ├── auth.py          # JWT utilities, password hashing, auth dependencies
│   ├── authz.py         # trip/session access rules (owner / member roles)
│   ├── users.py         # register, login, account, preferences, trips, sessions, members
│   ├── export.py        # PDF export
│   ├── share.py         # public read-only share links
│   ├── feedback.py      # ratings + free-text feedback
│   └── signals.py       # client-reported interaction signals
├── core/
│   ├── graph.py         # LangGraph wiring (main graph + compiler-only variant graph)
│   ├── orchestrator.py  # TravelOrchestrator: invoke + stream, A/B compare
│   ├── state.py         # AgentState TypedDict
│   ├── llm.py           # role-based LLM factory (OpenAI + flag-gated Gemini)
│   ├── nodes/
│   │   ├── interviewer.py  # extraction + deterministic slot-filling gate
│   │   ├── research.py     # food / activity / hotel research (config-driven)
│   │   ├── compiler.py     # itinerary writing + map geo payload
│   │   └── critic.py       # quality review + scoring
│   ├── logistics.py     # async geocoding + zone assignment / routing
│   ├── geo.py           # geocoding + distance helpers
│   ├── semantic_cache.py# pgvector semantic cache
│   ├── signals.py / signal_store.py  # implicit-signal scoring + persistence
│   ├── tokens.py / email.py          # auth-token lifecycle + transactional email
│   ├── pdf.py           # server-side HTML-to-PDF
│   ├── database.py      # SQLAlchemy models + connection pooling
│   └── …                # schemas, validation, history, ratelimit, logger
├── frontend/            # React 19 + Vite app (see frontend/ for its own layout)
├── migrations/          # Alembic migrations (baseline + feature migrations)
├── docs/                # how-it-works docs with diagrams
├── docker-compose.yml   # Postgres + backend + frontend
├── Dockerfile
├── DEPLOYMENT.md        # production runbook
├── PRIVACY.md
├── requirements.txt
├── init_db.py / run_api.py / cli.py
└── test_smoke.py
```

## Tests

```bash
# Backend unit tests. The default run excludes integration tests
# (addopts = -m 'not integration' in pyproject.toml), so it needs no DB or API keys.
pytest

# Integration tests (need live API keys / a database):
pytest -m integration

# Import + route smoke check:
python test_smoke.py

# Frontend tests (vitest):
npm --prefix frontend test
```

`eslint` is configured in `frontend/package.json` but is currently broken, so linting the frontend
is skipped; CI does not run it.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and on pull requests:

- **Backend:** black, ruff, and isort checks; `test_smoke.py`; then `pytest` (integration tests
  excluded). Lint tool versions are pinned to match `.pre-commit-config.yaml`.
- **Frontend:** `npm test` (vitest).

## Security

- JWT auth with bcrypt-hashed passwords; production refuses to boot on a default `JWT_SECRET_KEY`.
- Email-verification and password-reset tokens are stored only as SHA-256 hashes, single-use and
  expiring.
- Per-IP sliding-window rate limiting; explicit CORS origin allowlist (no wildcards).
- Pydantic input validation and length caps on user-supplied payloads.
- Internal errors are logged, not surfaced to clients.
- Trip/session edit access is gated before any session is created or mutated.

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgments

Built as part of the Mentor the Young program, as practice in AI agent systems and full-stack
engineering.
