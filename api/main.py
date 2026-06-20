"""FastAPI server with semantic cache monitoring and observability."""

import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from api.chat import router as chat_router
from api.export import router as export_router
from api.share import router as share_router
from api.users import router as users_router
from core.database import SessionLocal, engine, init_db
from core.logger import get_logger
from core.semantic_cache import get_cache_stats

logger = get_logger(__name__)

API_KEY = os.getenv("API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> str | None:
    """Validate API key if set. Skips auth when API_KEY env var is empty (dev mode)."""
    if not API_KEY:
        return None
    if not api_key or api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


_rate_limit_store: dict[str, list[float]] = {}
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "30"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    logger.info("Starting Travel Companion API...")

    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

    try:
        stats = get_cache_stats()
        if stats:
            logger.info("Semantic Cache Stats:")
            for category, data in stats.items():
                logger.info(f"  {category}: {data['entries']} entries, {data['total_uses']} uses")
    except Exception as e:
        logger.warning(f"Could not load cache stats: {e}")

    yield

    logger.info("Shutting down...")


app = FastAPI(
    title="Travel Companion API",
    description="AI-powered travel planning with semantic caching",
    version="1.0.0",
    lifespan=lifespan,
)

_allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)


_RATE_LIMIT_MAX_IPS = 10_000


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Per-IP sliding-window rate limiter. Skips health/liveness probes."""
    if request.url.path in ("/", "/health"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    window_start = now - RATE_LIMIT_WINDOW
    hits = _rate_limit_store.get(client_ip, [])
    hits = [t for t in hits if t > window_start]

    if len(hits) >= RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."},
        )

    hits.append(now)
    _rate_limit_store[client_ip] = hits

    if len(_rate_limit_store) > _RATE_LIMIT_MAX_IPS:
        stale = [ip for ip, ts in _rate_limit_store.items() if not ts or ts[-1] < window_start]
        for ip in stale:
            del _rate_limit_store[ip]

    return await call_next(request)


_metrics = {"requests_total": 0, "requests_by_path": {}, "errors_total": 0, "avg_latency_ms": 0.0, "_latency_sum": 0.0}


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Attach X-Request-ID / X-Response-Time-Ms headers and track aggregate metrics."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    start = time.time()

    response = await call_next(request)

    duration_ms = (time.time() - start) * 1000
    path = request.url.path

    _metrics["requests_total"] += 1
    _metrics["_latency_sum"] += duration_ms
    _metrics["avg_latency_ms"] = round(_metrics["_latency_sum"] / _metrics["requests_total"], 1)
    _metrics["requests_by_path"][path] = _metrics["requests_by_path"].get(path, 0) + 1

    if response.status_code >= 400:
        _metrics["errors_total"] += 1

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 1))

    logger.info(f"[{request_id}] {request.method} {path} -> {response.status_code} ({duration_ms:.0f}ms)")
    return response


app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(export_router, prefix="/api/export", tags=["export"])
app.include_router(share_router, prefix="/api/share", tags=["share"])
app.include_router(users_router, prefix="/api/users", tags=["users"])


@app.get("/")
async def root():
    """Liveness probe."""
    return {"status": "ok", "service": "Travel Companion API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """Deep health check — verifies database connectivity."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Health check DB failure: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected"},
        )

    return {"status": "healthy", "database": db_status}


@app.get("/api/cache/stats")
async def cache_stats(destination: str | None = None):
    """Semantic cache performance metrics, optionally filtered by destination."""
    try:
        stats = get_cache_stats(destination)

        total_entries = sum(s["entries"] for s in stats.values())
        total_uses = sum(s["total_uses"] for s in stats.values())
        hit_rate = (total_uses / total_entries * 100) if total_entries > 0 else 0

        return {
            "overall": {"total_entries": total_entries, "total_uses": total_uses, "hit_rate_pct": round(hit_rate, 1)},
            "by_category": stats,
        }
    except Exception as e:
        logger.error(f"Cache stats error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve cache stats.") from None


@app.get("/api/cache/inspect/{destination}")
async def inspect_cache(destination: str):
    """Detailed cache entries for a specific destination."""
    from sqlalchemy import text

    db = SessionLocal()
    try:
        entries = db.execute(
            text(
                """
            SELECT
                category, query_text, result_count, use_count,
                created_at, last_used,
                EXTRACT(EPOCH FROM (NOW() - created_at))/86400 as age_days,
                avg_rating/10.0 as avg_rating
            FROM semantic_cache
            WHERE destination = :dest
            ORDER BY use_count DESC
        """
            ),
            {"dest": destination},
        ).fetchall()

        return {
            "destination": destination,
            "cache_entries": [
                {
                    "category": row[0],
                    "query": row[1],
                    "results": row[2],
                    "uses": row[3],
                    "created": row[4].isoformat(),
                    "last_used": row[5].isoformat() if row[5] else None,
                    "age_days": round(row[6], 1),
                    "avg_rating": row[7],
                }
                for row in entries
            ],
        }
    except Exception as e:
        logger.error(f"Inspect cache error: {e}")
        raise HTTPException(status_code=500, detail="Failed to inspect cache.") from None
    finally:
        db.close()


@app.post("/api/cache/clear-stale")
async def clear_stale_cache(max_age_days: int = 60, _key: str | None = Depends(verify_api_key)):
    """Remove cache entries older than max_age_days (default 60)."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    db = SessionLocal()
    try:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

        result = db.execute(
            text("DELETE FROM semantic_cache WHERE created_at < :cutoff RETURNING id"), {"cutoff": cutoff}
        )
        deleted_count = result.rowcount

        db.commit()

        logger.info(f"Deleted {deleted_count} stale cache entries (older than {max_age_days} days)")

        return {"deleted_entries": deleted_count, "cutoff_date": cutoff.isoformat(), "max_age_days": max_age_days}
    except Exception as e:
        logger.error(f"Clear cache error: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear stale cache.") from None
    finally:
        db.close()


@app.get("/api/cache/test-similarity")
async def test_similarity(query1: str, query2: str):
    """Compare cosine similarity between two queries. Useful for debugging cache behavior."""
    import numpy as np

    from core.semantic_cache import embeddings

    try:
        vec1 = await embeddings.aembed_query(query1)
        vec2 = await embeddings.aembed_query(query2)

        similarity = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

        match_quality = (
            "Excellent (>90%)"
            if similarity > 0.9
            else "Good (80-90%)" if similarity > 0.8 else "Fair (70-80%)" if similarity > 0.7 else "Poor (<70%)"
        )

        return {
            "query1": query1,
            "query2": query2,
            "cosine_similarity": round(float(similarity), 4),
            "similarity_pct": f"{similarity:.1%}",
            "match_quality": match_quality,
            "would_hit_cache": similarity > 0.8,
        }
    except Exception as e:
        logger.error(f"Similarity test error: {e}")
        raise HTTPException(status_code=500, detail="Failed to compute similarity.") from None


@app.get("/api/metrics")
async def get_metrics(_key: str | None = Depends(verify_api_key)):
    """Aggregate request metrics. Requires API key."""
    return {
        "requests_total": _metrics["requests_total"],
        "errors_total": _metrics["errors_total"],
        "avg_latency_ms": _metrics["avg_latency_ms"],
        "requests_by_path": _metrics["requests_by_path"],
    }


@app.get("/api/debug/logs")
async def get_recent_logs(_key: str | None = Depends(verify_api_key)):
    """Last 100 lines from the application log file. Requires API key."""
    try:
        log_file = "logs/travel_companion.log"
        if not os.path.exists(log_file):
            return {"logs": [], "message": "No log file found"}

        with open(log_file) as f:
            lines = f.readlines()
            recent_logs = lines[-100:]

        return {"logs": [line.strip() for line in recent_logs], "count": len(recent_logs)}
    except Exception as e:
        logger.error(f"Get logs error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve logs.") from None


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))

    logger.info(f"Starting server on http://localhost:{port}")
    logger.info(f"API docs: http://localhost:{port}/docs")
    logger.info(f"Cache stats: http://localhost:{port}/api/cache/stats")
