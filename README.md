# Atlas Travel Companion

A production-grade multi-agent system for automated travel planning using LangGraph and semantic caching.

## Overview

Atlas is an AI-powered travel assistant that orchestrates multiple specialized agents to generate personalized, logically structured itineraries. The system implements Agentic RAG with semantic caching to balance response speed and data freshness while minimizing API costs.

### Key Features

- **Multi-Agent Orchestration**: Built on LangGraph StateGraph with 7 specialized nodes and conditional routing
- **Multi-Destination Support**: Plan trips across multiple cities (e.g., "Paris and Rome in 7 days")
- **React Frontend**: Real-time SSE streaming chat UI with Framer Motion animations
- **Semantic Caching**: PostgreSQL + pgvector embeddings for intelligent research data reuse
- **Intelligent Route Optimization**: Proximity zone grouping + nearest-neighbor algorithm
- **Async Pipeline**: Fully async graph execution — no event loop blocking
- **Observability**: Request tracing (X-Request-ID), per-endpoint latency metrics, aggregate /api/metrics
- **Security**: API key auth, per-IP rate limiting, CORS lockdown, sanitized error responses
- **Docker-Ready**: Single-command deployment with docker-compose (app + DB + frontend)

## Architecture

```
User Request
  -> FastAPI (api/main.py)
    -> TravelOrchestrator
      -> LangGraph StateGraph
        -> Interviewer (extract preferences)
        -> [Parallel] Food + Activity + Hotel Research
          -> Each checks Semantic Cache (pgvector) before Google Search
        -> Logistics Agent (async geocoding via Nominatim)
        -> Compiler (zone-optimized Markdown itinerary)
        -> Critic (QA review, may loop back)
      -> Response
    -> PostgreSQL persistence (sessions + trips)
```

### Agent Workflow

1. **Interviewer**: Extracts destination, duration, budget, and preferences from natural language
2. **Research Agents** (parallel execution):
   - Food Agent: Sources restaurants with Google Search Grounding
   - Activity Agent: Finds attractions matching user interests
   - Hotel Agent: Recommends accommodations within budget
3. **Logistics Agent**: Async geocoding of all locations with DB cache
4. **Compiler**: Generates day-by-day itinerary with zone-optimized routing
5. **Critic**: Validates output quality and triggers refinement if needed

### Semantic Cache (Agentic RAG)

The system implements a self-reflection layer:
- Query embeddings are compared against cached research using cosine similarity
- Cache decisions factor in similarity score, data age, and category-specific freshness thresholds
- New research results are automatically cached for future queries

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI, Pydantic v2 |
| AI Framework | LangGraph, LangChain |
| LLM | Google Gemini (2.5 Flash Lite, 2.0 Flash) |
| Database | PostgreSQL 16 + pgvector |
| Embeddings | Google text-embedding-004 |
| Geocoding | Geopy (Nominatim) via async executor |
| Frontend | React 19, Vite, Framer Motion, react-markdown |
| Containerization | Docker, docker-compose |

## Quick Start

### Option 1: Docker (Recommended)

```bash
cp .env.example .env
# Edit .env with your GEMINI_API_KEY

docker compose up --build
```

- API: `http://localhost:8000`
- Frontend: `http://localhost:3000`

### Option 2: Local Development

Prerequisites: Python 3.12+, PostgreSQL 15+ with pgvector extension.

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your GEMINI_API_KEY and DATABASE_URL

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
| `GEMINI_API_KEY` | Yes | - | Google Gemini API key |
| `DATABASE_URL` | Yes | `postgresql://postgres:postgres@localhost:5432/travel_companion` | PostgreSQL connection string |
| `API_KEY` | No | - | API authentication key (empty = no auth, dev mode) |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:5173` | Allowed frontend origins |
| `RATE_LIMIT_MAX` | No | `30` | Max requests per IP per window |
| `RATE_LIMIT_WINDOW` | No | `60` | Rate limit window in seconds |
| `USE_REACT_AGENT` | No | `false` | Enable ReAct agent mode for compiler |

## API Endpoints

### Core

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | No | Liveness probe |
| `GET` | `/health` | No | Deep health check (DB connectivity) |
| `POST` | `/api/chat` | Yes | Standard chat (non-streaming) |
| `POST` | `/api/chat/stream` | Yes | SSE streaming chat |

### Cache Management

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/cache/stats` | No | Cache performance metrics |
| `GET` | `/api/cache/inspect/{destination}` | No | Detailed cache entries |
| `POST` | `/api/cache/clear-stale` | Yes | Remove old cache entries |
| `GET` | `/api/cache/test-similarity` | No | Test embedding similarity |

### Observability

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/metrics` | Yes | Aggregate request metrics |
| `GET` | `/api/debug/logs` | Yes | Recent application logs |

Every response includes `X-Request-ID` and `X-Response-Time-Ms` headers for tracing.

### Chat Request Example

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"message": "Plan a 3-day trip to Paris on a medium budget", "history": []}'
```

## Project Structure

```
travel-companion/
├── api/
│   ├── main.py              # FastAPI app, security, observability
│   └── chat.py              # DB-backed chat router (/api/v2)
├── core/
│   ├── graph.py             # LangGraph workflow (multi-dest research)
│   ├── state.py             # AgentState TypedDict
│   ├── orchestrator.py      # TravelOrchestrator (invoke + stream)
│   ├── llm.py               # Role-based LLM factory
│   ├── schemas.py           # Pydantic models (multi-destination)
│   ├── tools.py             # LangChain tools (geocode, distance, zones)
│   ├── logistics.py         # Async geocoding + zone assignment
│   ├── semantic_cache.py    # PGVector semantic cache + RAG
│   ├── database.py          # SQLAlchemy models + connection pooling
│   └── logger.py            # Loguru configuration
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main chat application
│   │   ├── hooks/useChat.js # SSE streaming hook
│   │   └── components/      # Header, Welcome, Message, InputBar, StatusBar
│   ├── Dockerfile
│   └── package.json
├── Dockerfile
├── docker-compose.yml       # App + DB + Frontend
├── requirements.txt         # Pinned dependencies
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

### Code Quality

The project uses Black (line-length: 120), Ruff, isort, and mypy. Configuration is in `pyproject.toml`.

## Security

- **Authentication**: Optional API key via `X-API-Key` header (set `API_KEY` env var to enable)
- **Rate Limiting**: Per-IP, configurable window and max requests
- **CORS**: Explicit origin allowlist (no wildcards in production)
- **Error Handling**: Internal errors are logged but never exposed to clients
- **Health Checks**: `/health` endpoint verifies DB connectivity (returns 503 if down)

## Performance

- **Semantic Cache Hit Rate**: ~60-70% on repeated queries for the same destination
- **Average Latency**: ~15-20s for full itinerary generation (with cache: ~8-12s)
- **Connection Pooling**: SQLAlchemy pool with pre-ping and 30-min recycle
- **Async Throughout**: All LLM calls, geocoding, and DB operations are non-blocking

## License

MIT License

## Acknowledgments

Developed as part of the **Mentor the Young** program, focusing on practical application of AI agent systems and backend engineering principles.
