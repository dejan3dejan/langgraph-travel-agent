from dotenv import load_dotenv
from sqlalchemy import text

from core.database import SessionLocal

load_dotenv()

print("🔍 Testing semantic_cache connection...")

db = SessionLocal()

try:
    # Test 1: Count rows
    count = db.execute(text("SELECT COUNT(*) FROM semantic_cache")).scalar()
    print(f"✅ semantic_cache has {count} entries")

    # Test 2: Select all
    results = db.execute(
        text(
            """
        SELECT id, query_text, category, destination
        FROM semantic_cache
    """
        )
    ).fetchall()

    print("\n📋 Cache entries:")
    for row in results:
        print(f"  - {row[0]}: {row[1]} ({row[2]} in {row[3]})")

    # Test 3: Test vector query
    print("\n🧪 Testing vector similarity...")
    similarity_test = db.execute(
        text(
            """
        SELECT
            id,
            1 - (query_embedding <=> array_fill(0.5, ARRAY[768])::vector) as sim
        FROM semantic_cache
        WHERE id = 'test_berlin_restaurants'
    """
        )
    ).fetchone()

    if similarity_test:
        print(f"✅ Vector search works! Similarity: {similarity_test[1]:.4f}")

    print("\n🎉 All tests passed!")

except Exception as e:
    print(f"❌ Error: {e}")

finally:
    db.close()
