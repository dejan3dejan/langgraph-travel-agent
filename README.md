# Atlas Travel Companion

A multi-agent system for automated travel planning, built on LangGraph with a hybrid LLM strategy and semantic caching.

## Overview

Atlas is an AI-powered travel assistant that orchestrates multiple specialized agents to generate personalized, logically structured itineraries. It implements Agentic RAG with semantic caching to balance response speed and data freshness while minimizing API costs.

### Key Features

- **Multi-Agent Orchestration**: LangGraph StateGraph with 7 specialized nodes and conditional routing
- **Hybrid LLM Strategy**: OpenAI for conversation/writing, Google Gemini (with live Google Search grounding) for research
- **User Accounts**: JWT authentication, saved preferences, persisted trips and chat sessions
- **Multi-Destination Support**: Plan trips across multiple cities (e.g., "Paris and Rome in 7 days")
- **React Frontend**: Real-time SSE streaming chat UI with Framer Motion animations
- **Semantic Caching**: PostgreSQL + pgvector embeddings for intelligent research data reuse
- **Route Optimization**: Proximity-zone grouping + nearest-neighbor day planning
- **Async Pipeline**: Fully async graph execution — no event loop blocking
- **Observability**: Request tracing (X-Request-ID), per-endpoint latency, aggregate `/api/metrics`
- **CI**: GitHub Actions runs linting and smoke tests on every push and PR
- **Docker-Ready**: Single-command deployment with docker-compose (app + DB + frontend)

## Architecture

```
User Request
  -> FastAPI (api/main.py)
    -> TravelOrchestrator
      -> LangGraph StateGraph
        -> Interviewer (profile the traveler, extract preferences)
        -> [Parallel] Food + Activity + Hotel Research
          -> Each checks Semantic Cache (pgvector) before Gemini + Google Search
        -> Logistics Agent (async geocoding via Nominatim)
        -> Compiler (zone-optimized Markdown itinerary)
        -> Critic (QA review, may loop back to research or compiler)
      -> Response
    -> PostgreSQL persistence (users, sessions, trips)
```

### Agent Workflow

1. **Interviewer**: Builds a traveler profile through conversation — destination, duration, budget, who's going, trip type, timing — then triggers research.
2. **Research Agents** (parallel execution):
   - Food Agent: Sources restaurants via Gemini + Google Search grounding
   - Activity Agent: Finds attractions matching user interests
   - Hotel Agent: Recommends accommodations within budget
3. **Logistics Agent**: Async geocoding of all locations with a DB cache
4. **Compiler**: Generates a day-by-day itinerary with zone-optimized routing
5. **Critic**: Validates output quality; loops back to research or compiler if needed

The pipeline lives in `core/graph.py` (wiring) and `core/nodes/` (the node implementations).

### Hybrid LLM Strategy

Each pipeline role is assigned the best-fit model (`core/llm.py`):

| Role | Model | Why |
|---|---|---|
| Interviewer | OpenAI GPT-4o-mini | Natural conversational tone |
| Compiler | OpenAI GPT-4o-mini | Strong long-form writing |
| Research | Google Gemini 2.5 Flash | Built-in Google Search grounding for live data |
| Extraction | Google Gemini 2.5 Flash Lite | Cheap, fast structured output |
| Critic | Google Gemini 2.5 Flash Lite | Lightweight quality judgment |

Gemini handles research because its Google Search grounding returns current data; GPT-4o-mini's training cutoff makes it unsuitable for live prices and availability.

### Semantic Cache (Agentic RAG)

A self-reflection layer that avoids redundant research:
- Query embeddings are compared against cached research using cosine similarity (pgvector)
- Cache decisions factor in similarity score, data age, and category-specific freshness thresholds (hotels 14d, restaurants 30d, activities 45d)
- New research results are automatically cached for future queries

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI, Pydantic v2 |
| AI Framework | LangGraph, LangChain |
| LLMs | OpenAI GPT-4o-mini + Google Gemini 2.5 Flash / Flash Lite |
| Embeddings | OpenAI text-embedding-3-small (1536-dim) |
| Database | PostgreSQL 16 + pgvector |
| Auth | JWT (python-jose), bcrypt |
| Geocoding | Geopy (Nominatim) via async executor |
| Frontend | React 19, Vite, Framer Motion, react-markdown |
| Containerization | Docker, docker-compose |
| CI | GitHub Actions |

## Quick Start

### Option 1: Docker (Recommended)

```bash
cp .env.example .env
# Edit .env with your OPENAI_API_KEY and GEMINI_API_KEY

docker compose up --build
```

- API: `http://localhost:8000`
- Frontend: `http://localhost:3000`

### Option 2: Local Development

Prerequisites: Python 3.12+, PostgreSQL 16+ with the pgvector extension.

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your API keys and DATABASE_URL

python init_db.py
python run_api.py
```

### Option 3: Frontend Development

```bash
cd frontend
npm install
npm run dev
```

The frontend proxies `/api` requests to `localhost:8000` automatically.

### Option 4: CLI Mode

```bash
python cli.py
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | - | OpenAI API key (interviewer, compiler, embeddings) |
| `GEMINI_API_KEY` | Yes | - | Google Gemini API key (research, extraction, critic) |
| `DATABASE_URL` | Yes | `postgresql://postgres:postgres@localhost:5432/travel_companion` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | Prod | `dev-secret-change-in-production` | Secret for signing JWTs (set a strong value in production) |
| `JWT_EXPIRE_MINUTES` | No | `1440` | Access token lifetime in minutes |
| `API_KEY` | No | - | Admin-endpoint key via `X-API-Key` (empty = dev mode) |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:5173` | Allowed frontend origins |
| `RATE_LIMIT_MAX` | No | `30` | Max requests per IP per window |
| `RATE_LIMIT_WINDOW` | No | `60` | Rate limit window in seconds |
| `USE_REACT_AGENT` | No | `false` | Enable ReAct agent mode for the compiler |

## API Endpoints

### Chat

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chat` | Optional | Standard chat (non-streaming) |
| `POST` | `/api/chat/stream` | Optional | SSE streaming chat |

Chat works anonymously; with a Bearer token, sessions and trips are owned by the user.

### Auth & Users

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/users/register` | No | Create an account, returns a JWT |
| `POST` | `/api/users/login` | No | Authenticate, returns a JWT |
| `GET` | `/api/users/me` | Yes | Current user profile |
| `GET` | `/api/users/preferences` | Yes | Saved travel defaults |
| `PUT` | `/api/users/preferences` | Yes | Update saved defaults |
| `GET` | `/api/users/trips` | Yes | List saved trips |
| `GET` | `/api/users/trips/{id}` | Yes | Full itinerary detail |
| `DELETE` | `/api/users/trips/{id}` | Yes | Delete a trip |
| `GET` | `/api/users/sessions` | Yes | List chat sessions |
| `DELETE` | `/api/users/sessions/{id}` | Yes | Delete a session and its trips |

### Cache & Observability

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | No | Liveness probe |
| `GET` | `/health` | No | Deep health check (DB connectivity) |
| `GET` | `/api/cache/stats` | No | Cache performance metrics |
| `GET` | `/api/cache/inspect/{destination}` | No | Detailed cache entries |
| `POST` | `/api/cache/clear-stale` | Yes | Remove old cache entries |
| `GET` | `/api/cache/test-similarity` | No | Test embedding similarity |
| `GET` | `/api/metrics` | Yes | Aggregate request metrics |
| `GET` | `/api/debug/logs` | Yes | Recent application logs |

Every response includes `X-Request-ID` and `X-Response-Time-Ms` headers for tracing.

### Examples

```bash
# Anonymous chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Plan a 3-day trip to Paris on a medium budget"}'

# Register, then chat as that user
curl -X POST http://localhost:8000/api/users/register \
  -H "Content-Type: application/json" \
  -d '{"email": "me@example.com", "username": "me", "password": "secret123"}'

curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "Plan a romantic week in Rome"}'
```

## Project Structure

```
travel-companion/
├── api/
│   ├── main.py              # FastAPI app, middleware, cache/metrics endpoints
│   ├── chat.py              # Chat + streaming endpoints (DB-persisted)
│   ├── auth.py              # JWT utilities, password hashing, auth dependencies
│   └── users.py             # Register, login, preferences, trips, sessions
├── core/
│   ├── graph.py             # LangGraph workflow wiring
│   ├── state.py             # AgentState TypedDict
│   ├── orchestrator.py      # TravelOrchestrator (invoke + stream)
│   ├── llm.py               # Hybrid role-based LLM factory (OpenAI + Gemini)
│   ├── schemas.py           # Pydantic models
│   ├── tools.py             # LangChain tools (geocode, distance, zones, routes)
│   ├── logistics.py         # Async geocoding + zone assignment
│   ├── semantic_cache.py    # pgvector semantic cache + RAG
│   ├── database.py          # SQLAlchemy models + connection pooling
│   ├── logger.py            # Loguru configuration
│   └── nodes/
│       ├── interviewer.py   # Conversation + preference extraction
│       ├── research.py      # Food / activity / hotel research (config-driven)
│       ├── compiler.py      # Itinerary writing + route optimization
│       └── critic.py        # Quality review + scoring
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main chat application
│   │   ├── hooks/useChat.js # SSE streaming hook
│   │   └── components/      # Header, Welcome, Message, InputBar, StatusBar
│   ├── Dockerfile
│   └── package.json
├── .github/workflows/ci.yml # Lint + smoke tests
├── Dockerfile
├── docker-compose.yml       # App + DB + Frontend
├── requirements.txt
├── .env.example
├── init_db.py
├── run_api.py
├── cli.py                   # Rich terminal interface
└── test_smoke.py            # Import + unit smoke tests
```

## Development

### Running Tests

```bash
# Smoke tests (no DB/API required)
python test_smoke.py

# Full test suite
pytest
```

### Continuous Integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and on pull requests:
black, ruff, isort, and the smoke suite. Tool versions are pinned to match
`.pre-commit-config.yaml` so local hooks and CI never disagree.

### Code Quality

The project uses Black (line-length 120), Ruff, isort, and mypy, all configured in
`pyproject.toml` and enforced via pre-commit hooks.

## Security

- **Authentication**: JWT-based user accounts (bcrypt-hashed passwords); optional `X-API-Key` for admin endpoints
- **Rate Limiting**: Per-IP sliding window, configurable
- **CORS**: Explicit origin allowlist (no wildcards)
- **Input Validation**: Message length limits via Pydantic
- **Error Handling**: Internal errors are logged but never exposed to clients
- **Health Checks**: `/health` verifies DB connectivity (returns 503 if down)

## License

MIT License

## Acknowledgments

Developed as part of the **Mentor the Young** program, focusing on practical application of AI agent systems and backend engineering principles.
