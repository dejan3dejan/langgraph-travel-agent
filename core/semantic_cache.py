"""
Semantic Research Cache using PGVector
Implements Agentic RAG + Self-Reflection + Contextual RAG
FIXED: Parameter binding for vector operations
"""

import json
from datetime import datetime, timedelta

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sqlalchemy import text

from .database import SessionLocal
from .logger import get_logger

logger = get_logger(__name__)

# Initialize Embeddings (Gemini text-embedding-004)
embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", task_type="retrieval_document")


# ============================================================================
# CORE RAG FUNCTIONS
# ============================================================================


async def semantic_search(
    query: str, category: str, destination: str, similarity_threshold: float = 0.80, max_age_days: int = 30
) -> dict | None:
    """
    SELF-REFLECTION RAG: Check if we have relevant cached data.

    Args:
        query: User's search query (e.g., "best pizza in Rome")
        category: "restaurants", "activities", or "hotels"
        destination: City/region name
        similarity_threshold: Minimum cosine similarity (0.80 = 80% match)
        max_age_days: Maximum age of cached data to consider

    Returns:
        Cache hit dict or None
    """
    logger.info(f"🔍 Self-Reflection: Checking semantic cache for '{query}'...")

    try:
        # 1. Generate query embedding
        query_vec = await embeddings.aembed_query(query)

        # 2. Convert list to PostgreSQL array format
        query_vec_str = "[" + ",".join(map(str, query_vec)) + "]"

        # 3. Search PGVector with filters
        db = SessionLocal()
        cutoff_date = datetime.utcnow() - timedelta(days=max_age_days)

        # FIX: Use string formatting for vector cast, params for others
        sql_query = text(
            f"""
            SELECT
                id, query_text, results, created_at, use_count,
                1 - (query_embedding <=> '{query_vec_str}'::vector) as similarity
            FROM semantic_cache
            WHERE category = :category
              AND destination = :destination
              AND created_at > :cutoff_date
              AND 1 - (query_embedding <=> '{query_vec_str}'::vector) > :threshold
            ORDER BY similarity DESC
            LIMIT 1
        """
        )

        result = db.execute(
            sql_query,
            {
                "category": category,
                "destination": destination,
                "cutoff_date": cutoff_date,
                "threshold": similarity_threshold,
            },
        ).fetchone()

        if result:
            cache_id, original_query, cached_results, created, uses, similarity = result
            age_days = (datetime.utcnow() - created).days

            logger.info(
                f"✅ CACHE HIT! Similarity: {similarity:.2%}, "
                f"Age: {age_days}d, Uses: {uses}, "
                f"Original: '{original_query}'"
            )

            # Update usage stats
            update_sql = text(
                """
                UPDATE semantic_cache
                SET use_count = use_count + 1, last_used = :now
                WHERE id = :id
            """
            )
            db.execute(update_sql, {"now": datetime.utcnow(), "id": cache_id})
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
            logger.info("❌ CACHE MISS - Will trigger Google Search")
            return None

    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return None
    finally:
        db.close()


async def cache_research_results(
    query: str, category: str, destination: str, results: list[dict], freshness_days: int = 30
) -> bool:
    """
    Store research results in semantic cache.

    Args:
        query: Original search query
        category: "restaurants", "activities", "hotels"
        destination: City/region
        results: List of structured results
        freshness_days: How long this data stays fresh

    Returns:
        Success boolean
    """
    if not results:
        logger.warning("No results to cache")
        return False

    logger.info(f"💾 Caching {len(results)} {category} for '{destination}'...")

    try:
        # 1. Generate embedding
        query_vec = await embeddings.aembed_query(query)
        query_vec_str = "[" + ",".join(map(str, query_vec)) + "]"

        # 2. Calculate quality metric
        ratings = [r.get("rating", 0) for r in results if r.get("rating")]
        avg_rating = int(sum(ratings) / len(ratings) * 10) if ratings else 0

        # 3. Generate unique ID
        cache_id = f"{category}_{destination}_{hash(query)}"

        # 4. Insert or update cache entry
        db = SessionLocal()

        # FIX: Use f-string for vector, params for others
        upsert_sql = text(
            f"""
            INSERT INTO semantic_cache (
                id, query_text, query_embedding, category, destination,
                results, result_count, avg_rating, freshness_days,
                created_at, last_used, use_count
            ) VALUES (
                :id, :query_text, '{query_vec_str}'::vector, :category, :destination,
                :results, :result_count, :avg_rating, :freshness_days,
                :created_at, :last_used, :use_count
            )
            ON CONFLICT (id) DO UPDATE SET
                query_text = EXCLUDED.query_text,
                query_embedding = EXCLUDED.query_embedding,
                results = EXCLUDED.results,
                result_count = EXCLUDED.result_count,
                avg_rating = EXCLUDED.avg_rating,
                created_at = EXCLUDED.created_at,
                use_count = 0
        """
        )

        db.execute(
            upsert_sql,
            {
                "id": cache_id,
                "query_text": query,
                "category": category,
                "destination": destination,
                "results": json.dumps(results, ensure_ascii=False),
                "result_count": len(results),
                "avg_rating": avg_rating,
                "freshness_days": freshness_days,
                "created_at": datetime.utcnow(),
                "last_used": datetime.utcnow(),
                "use_count": 0,
            },
        )

        db.commit()
        db.close()

        logger.info(f"✅ Cached successfully (avg rating: {avg_rating/10:.1f})")
        return True

    except Exception as e:
        logger.error(f"Failed to cache results: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def get_cache_stats(destination: str | None = None) -> dict:
    """Get cache performance metrics."""
    db = SessionLocal()
    try:
        if destination:
            sql = text(
                """
                SELECT category, COUNT(*), SUM(use_count), AVG(avg_rating/10.0)
                FROM semantic_cache
                WHERE destination = :destination
                GROUP BY category
            """
            )
            results = db.execute(sql, {"destination": destination}).fetchall()
        else:
            sql = text(
                """
                SELECT category, COUNT(*), SUM(use_count), AVG(avg_rating/10.0)
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


# ============================================================================
# AGENTIC DECISION MAKER
# ============================================================================


async def should_use_cache(cache_hit: dict | None, category: str) -> tuple[bool, str]:
    """
    AGENTIC RAG: Decide whether to use cache or search Google.

    Returns:
        (use_cache: bool, reason: str)
    """
    if not cache_hit:
        return False, "no_cache_entry"

    similarity = cache_hit.get("similarity", 0)
    age_days = cache_hit.get("age_days", 999)

    # Category-specific freshness rules
    max_ages = {"restaurants": 30, "hotels": 14, "activities": 45}

    max_age = max_ages.get(category, 30)

    # Decision Matrix
    if similarity >= 0.90 and age_days <= max_age:
        return True, f"high_confidence (sim={similarity:.0%}, age={age_days}d)"

    elif similarity >= 0.80 and age_days <= max_age // 2:
        return True, f"good_match (sim={similarity:.0%}, age={age_days}d)"

    elif age_days > max_age:
        return False, f"stale_data (age={age_days}d > max={max_age}d)"

    else:
        return False, f"low_confidence (sim={similarity:.0%})"


# ============================================================================
# PROGRESSIVE REFRESH (Advanced)
# ============================================================================


async def progressive_refresh(cache_hit: dict, category: str, search_func) -> list[dict]:
    """
    Hybrid approach: Use cache + fetch 1 new result to stay fresh.

    Args:
        cache_hit: Existing cache data
        category: Data category
        search_func: Function to call Google Search (async)

    Returns:
        Combined results (cached + 1 new)
    """
    cached_results = cache_hit["results"]
    age_days = cache_hit["age_days"]

    # If data is <14 days old, just use cache
    if age_days < 14:
        logger.info("📦 Using 100% cache (fresh enough)")
        return cached_results

    # If 14-30 days old, add 1 fresh result
    logger.info("🔄 Progressive refresh: 80% cache + 20% new search")

    try:
        # Search for just 1 new result
        new_results = await search_func(limit=1)

        # Combine: cached (top 2) + new (1)
        return cached_results[:2] + new_results[:1]
    except Exception as e:
        logger.warning(f"Progressive refresh failed: {e}, using full cache")
        return cached_results
