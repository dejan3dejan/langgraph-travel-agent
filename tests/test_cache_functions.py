# test_cache_functions.py
import asyncio

from core.semantic_cache import cache_research_results, semantic_search


async def test():
    # Test 1: Cache miss (prvo pretraživanje)
    result = await semantic_search(query="best pizza in Rome", category="restaurants", destination="Rome")
    print(f"First search (cache miss): {result}")  # None

    # Test 2: Cache result
    await cache_research_results(
        query="best pizza in Rome",
        category="restaurants",
        destination="Rome",
        results=[{"name": "Pizzeria da Baffetto", "rating": 4.5}, {"name": "Emma Pizzeria", "rating": 4.6}],
        freshness_days=30,
    )
    print("✅ Results cached")

    # Test 3: Cache hit (drugo pretraživanje)
    result = await semantic_search(
        query="top pizza places in Rome",  # Slična fraza
        category="restaurants",
        destination="Rome",
        similarity_threshold=0.75,
    )
    print(f"Second search (cache hit): {result}")
    print(f"  Similarity: {result['similarity']:.2%}")
    print(f"  Results: {len(result['results'])} restaurants")


asyncio.run(test())
