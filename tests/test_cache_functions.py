# test_cache_functions.py
import pytest
from sqlalchemy import text

from core.database import SessionLocal
from core.semantic_cache import cache_research_results, semantic_search


@pytest.mark.asyncio
async def test_cache_functions_flow():
    # 0. Cleanup DB for this test query
    db = SessionLocal()
    db.execute(text("DELETE FROM semantic_cache WHERE query_text LIKE '%pizza in Rome%'"))
    db.commit()
    db.close()

    # Test 1: Cache miss (prvo pretraživanje)
    print("\nTesting cache miss...")
    result = await semantic_search(query="best pizza in Rome", category="restaurants", destination="Rome")
    print(f"First search result: {result}")
    assert result is None

    # Test 2: Cache result
    print("\nCaching results...")
    await cache_research_results(
        query="best pizza in Rome",
        category="restaurants",
        destination="Rome",
        results=[{"name": "Pizzeria da Baffetto", "rating": 4.5}, {"name": "Emma Pizzeria", "rating": 4.6}],
        freshness_days=30,
    )
    print("Results cached")

    # Test 3: Cache hit (drugo pretraživanje)
    print("\nTesting cache hit...")
    result = await semantic_search(
        query="top pizza places in Rome",  # Slična fraza
        category="restaurants",
        destination="Rome",
        similarity_threshold=0.75,
    )
    print(f"Second search result: {result}")
    assert result is not None
    assert result["hit"] is True
    print(f"  Similarity: {result['similarity']:.2%}")
    print(f"  Results: {len(result['results'])} restaurants")

    # Test 4: Bad query (unrelated)
    print("\nTesting unrelated query...")
    result_unrelated = await semantic_search(query="how to build a rocket", category="restaurants", destination="Rome")
    print(f"Unrelated search: {result_unrelated}")
    assert result_unrelated is None

    # Test 5: Empty DB (temporary truncate)
    print("\nTesting empty database...")
    db = SessionLocal()
    try:
        # Use a transaction to truncate, but we must commit because semantic_search
        # opens its own session and would deadlock waiting for our AccessExclusiveLock.
        db.execute(text("DELETE FROM semantic_cache"))
        db.commit()

        result_empty = await semantic_search(query="best pizza in Rome", category="restaurants", destination="Rome")
        print(f"Empty DB search: {result_empty}")
        assert result_empty is None

        print("Empty DB test passed")
    except Exception as e:
        print(f"Empty DB test failed: {e}")
        raise
    finally:
        db.close()
