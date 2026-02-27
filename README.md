# Atlas Travel Companion

A production-grade multi-agent system for automated travel planning using LangGraph and semantic caching.

## Overview

Atlas is an AI-powered travel assistant that orchestrates multiple specialized agents to generate personalized, logically structured itineraries. The system implements Agentic RAG with semantic caching to balance response speed and data freshness while minimizing API costs.

### Key Features

- **Multi-Agent Orchestration**: Built on LangGraph, with specialized agents for interviewing, research, logistics, and itinerary compilation
- **Semantic Caching**: PostgreSQL + pgvector implementation that uses embeddings to retrieve relevant cached research data
- **Intelligent Route Optimization**: Mathematical grouping of activities by proximity zones to minimize travel time
- **Automated Evaluation**: LLM-as-a-Judge benchmarking system to measure accuracy and performance
- **Context-Aware Planning**: Personalization based on traveler profile (age, trip type, budget, group size)

## Architecture

### Agent Workflow

1. **Interviewer Agent**: Extracts destination, duration, budget, and preferences from natural language
2. **Research Agents** (parallel execution):
   - Food Agent: Sources restaurants with grounding via Google Search
   - Activity Agent: Finds attractions matching user interests
   - Hotel Agent: Recommends accommodations within budget
3. **Logistics Agent**: Geocodes all locations and calculates proximity zones
4. **Compiler Agent**: Generates day-by-day itinerary with optimized routing
5. **Critic Agent**: Validates output quality and triggers refinement if needed

### Semantic Cache (Agentic RAG)

The system implements a self-reflection layer:
- Query embeddings are compared against cached research using cosine similarity
- Cache decisions factor in similarity score, data age, and category-specific freshness thresholds
- New research results are automatically cached for future queries

## Tech Stack

- **Backend**: FastAPI, Pydantic
- **AI Framework**: LangGraph, LangChain
- **LLM**: Google Gemini (2.5 Flash, 2.5 Pro)
- **Database**: PostgreSQL with pgvector extension
- **Embeddings**: Google Generative AI (text-embedding-004)
- **Geocoding**: Geopy (Nominatim)

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 15+ with pgvector extension
- Google Gemini API key

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/travel-companion.git
cd travel-companion
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
# .env
GEMINI_API_KEY=your_key_here
DATABASE_URL=postgresql://user:password@localhost:5432/travel_companion
```

4. Initialize the database:
```bash
python init_db.py
```

5. Run the API server:
```bash
python run_api.py
```

The server will be available at `http://localhost:8000`.

## Usage

### API Endpoint

**POST** `/chat`

Request body:
```json
{
  "message": "I want to visit Paris for 3 days",
  "history": []
}
```

Response:
```json
{
  "response": "Great! I'm researching your trip now...",
  "history": [...],
  "logs": [...],
  "itinerary": "# 3-Day Trip to Paris\n\n..."
}
```

### CLI Mode

```bash
python cli.py
```

## Benchmarking

The project includes an automated evaluation framework that grades itineraries using an LLM-as-a-Judge approach.

### Running Benchmarks

```bash
cd tests
python benchmark.py --limit 10
```

This will:
- Execute test scenarios from `dataset.json`
- Generate itineraries for each scenario
- Grade outputs based on predefined criteria
- Track latency, token usage, and geocoding success rates

### Metrics Tracked

- Per-node latency (interviewer, research, compiler, critic)
- Total token consumption
- Geocoding success rates (exact match, neighborhood fallback, failures)
- Overall itinerary quality score

Results are saved to `benchmark_results.json` and `benchmark_summary.json`.

## Project Structure

```
travel-companion/
├── core/
│   ├── graph.py           # LangGraph workflow definition
│   ├── semantic_cache.py  # Semantic caching + RAG logic
│   ├── database.py        # SQLAlchemy models and DB session
│   ├── llm.py             # LLM configuration and role assignment
│   ├── orchestrator.py    # Main orchestration logic
│   ├── schemas.py         # Pydantic models for structured output
│   ├── tools.py           # Route optimization and utility functions
│   └── logistics.py       # Geocoding and distance calculations
├── api/
│   ├── main.py            # FastAPI application
│   └── chat.py            # Chat endpoint implementation
├── tests/
│   ├── benchmark.py       # Automated evaluation suite
│   ├── dataset.json       # Test scenarios
│   └── analyze_results.py # Performance analysis tools
├── migrations/
│   └── add_semantic_cache.py
├── init_db.py
├── run_api.py
└── requirements.txt
```

## Development

### Code Quality

The project uses:
- **Black** for code formatting (line length: 120)
- **Ruff** for linting
- **isort** for import sorting
- **mypy** for type checking (optional)

Pre-commit hooks are configured via `.pre-commit-config.yaml`.

### Running Tests

```bash
# Unit tests
pytest tests/test_semantic_cache.py

# Integration benchmarks
python tests/benchmark.py
```

## Performance Optimization

- **Semantic Cache Hit Rate**: ~60-70% on repeated queries for the same destination
- **Average Latency**: ~15-20s for full itinerary generation (with cache hits: ~8-12s)
- **Token Efficiency**: Caching reduces token usage by ~40% on average

## Roadmap

- [ ] Frontend interface (React + streaming SSE)
- [ ] Multi-destination support (e.g., "Paris and Rome in 7 days")
- [ ] Real-time price fetching integration
- [ ] User authentication and itinerary saving
- [ ] Export to PDF/Calendar formats

## License

MIT License

## Acknowledgments

Developed as part of the **Mentor the Young** program, focusing on practical application of AI agent systems and backend engineering principles.
