"""Semantic research cache using PGVector for Agentic RAG with self-reflection."""

import json
import os
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sqlalchemy import text

from .database import SessionLocal
from .logger import get_logger

load_dotenv()

logger = get_logger(__name__)


class CacheError(Exception):
    pass


def to_pgvector(vec: list[float]) -> str:
    """Format a float list as a pgvector literal, e.g. '[0.1,0.2,...]'."""
    return "[" + ",".join(map(str, vec)) + "]"


embeddings = GoogleGenerativeAIEmbeddings(
    model="models/text-embedding-004",
    task_type="retrieval_document",
    google_api_key=os.getenv("GEMINI_API_KEY"),
)


async def semantic_search(
    query: str, category: str, destination: str, similarity_threshold: float = 0.80, max_age_days: int = 30
) -> dict | None:
    """Check semantic cache for a relevant hit using cosine similarity."""
    logger.info(f"Self-Reflection: Checking semantic cache for '{query}'...")
    db = None

    try:
        query_vec = await embeddings.aembed_query(query)

        db = SessionLocal()
        cutoff_date = datetime.now(UTC) - timedelta(days=max_age_days)

        sql_query = text(
            """
            SELECT
                id, query_text, results, created_at, use_count,
                1 - (query_embedding <=> CAST(:query_vec AS vector)) as similarity
            FROM semantic_cache
            WHERE category = :category
              AND destination = :destination
              AND created_at > :cutoff_date
              AND 1 - (query_embedding <=> CAST(:query_vec AS vector)) > :threshold
            ORDER BY similarity DESC
            LIMIT 1
        """
        )

        result = db.execute(
            sql_query,
            {
                "query_vec": to_pgvector(query_vec),
                "category": category,
                "destination": destination,
                "cutoff_date": cutoff_date,
                "threshold": similarity_threshold,
            },
        ).fetchone()

        if result:
            cache_id, original_query, cached_results, created, uses, similarity = result

            # DB may return naive datetime — make it tz-aware for comparison
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)

            age_days = (datetime.now(UTC) - created).days

            logger.info(
                f"CACHE HIT! Similarity: {similarity:.2%}, "
                f"Age: {age_days}d, Uses: {uses}, "
                f"Original: '{original_query}'"
            )

            update_sql = text(
                """
                UPDATE semantic_cache
                SET use_count = use_count + 1, last_used = :now
                WHERE id = :id
            """
            )
            db.execute(update_sql, {"now": datetime.now(UTC), "id": cache_id})
            db.commit()

            return {
                "hit": True,
                "results": json.loads(cached_results),
                "similarity": similarity,
                "age_days": age_days,
                "source": "semantic_cache",
                "original_query": original_query,
            }
        else:
            logger.info("CACHE MISS - Will trigger Google Search")
            return None

    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        import traceback

        logger.error(traceback.format_exc())
        raise CacheError(f"Semantic search failed: {e}") from e
    finally:
        if db:
            db.close()


async def cache_research_results(
    query: str, category: str, destination: str, results: list[dict], freshness_days: int = 30
) -> bool:
    """Store research results in semantic cache with embedding for future retrieval."""
    if not results:
        logger.warning("No results to cache")
        return False

    logger.info(f"Caching {len(results)} {category} for '{destination}'...")
    db = None

    try:
        query_vec = await embeddings.aembed_query(query)

        ratings = [r.get("rating", 0) for r in results if r.get("rating")]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        cache_id = f"{category}_{destination}_{hash(query)}"

        db = SessionLocal()

        upsert_sql = text(
            """
            INSERT INTO semantic_cache (
                id, query_text, query_embedding, category, destination,
                results, result_count, avg_rating, freshness_days,
                created_at, last_used, use_count
            ) VALUES (
                :id, :query_text, CAST(:query_vec AS vector), :category, :destination,
                :results, :result_count, :avg_rating, :freshness_days,
                :created_at, :last_used, :use_count
            )
            ON CONFLICT (id) DO UPDATE SET
                query_text = EXCLUDED.query_text,
                query_embedding = EXCLUDED.query_embedding,
                results = EXCLUDED.results,
                result_count = EXCLUDED.result_count,
                avg_rating = EXCLUDED.avg_rating,
                use_count = 0
        """
        )

        db.execute(
            upsert_sql,
            {
                "id": cache_id,
                "query_text": query,
                "query_vec": to_pgvector(query_vec),
                "category": category,
                "destination": destination,
                "results": json.dumps(results, ensure_ascii=False),
                "result_count": len(results),
                "avg_rating": avg_rating,
                "freshness_days": freshness_days,
                "created_at": datetime.now(UTC),
                "last_used": datetime.now(UTC),
                "use_count": 0,
            },
        )

        db.commit()
        logger.info(f"Cached successfully (avg rating: {avg_rating/10:.1f})")
        return True

    except Exception as e:
        logger.error(f"Failed to cache results: {e}")
        import traceback

        logger.error(traceback.format_exc())
        raise CacheError(f"Failed to cache results: {e}") from e
    finally:
        if db:
            db.close()


def get_cache_stats(destination: str | None = None) -> dict:
    """Get cache performance metrics."""
    db = SessionLocal()
    try:
        if destination:
            sql = text(
                """
                SELECT category, COUNT(*), SUM(use_count), AVG(avg_rating)
                FROM semantic_cache
                WHERE destination = :destination
                GROUP BY category
            """
            )
            results = db.execute(sql, {"destination": destination}).fetchall()
        else:
            sql = text(
                """
                SELECT category, COUNT(*), SUM(use_count), AVG(avg_rating)
                FROM semantic_cache
                GROUP BY category
            """
            )
            results = db.execute(sql).fetchall()

        return {
            row[0]: {"entries": row[1], "total_uses": row[2] or 0, "avg_rating": round(row[3], 1) if row[3] else 0}
            for row in results
        }
    finally:
        db.close()


async def should_use_cache(cache_hit: dict | None, category: str) -> tuple[bool, str]:
    """Decide whether a cache hit is fresh and relevant enough to skip a live search."""
    if not cache_hit:
        return False, "no_cache_entry"

    similarity = cache_hit.get("similarity", 0)
    age_days = cache_hit.get("age_days", 999)

    # Hotels go stale fastest (pricing), activities are most stable
    max_ages = {"restaurants": 30, "hotels": 14, "activities": 45}
    max_age = max_ages.get(category, 30)

    if similarity >= 0.90 and age_days <= max_age:
        return True, f"high_confidence (sim={similarity:.0%}, age={age_days}d)"

    elif similarity >= 0.80 and age_days <= max_age // 2:
        return True, f"good_match (sim={similarity:.0%}, age={age_days}d)"

    elif age_days > max_age:
        return False, f"stale_data (age={age_days}d > max={max_age}d)"

    else:
        return False, f"low_confidence (sim={similarity:.0%})"
