import os

from dotenv import load_dotenv  # ⬅️ DODAJ OVO!
from sqlalchemy import create_engine, text

# Load environment variables FIRST
load_dotenv()  # ⬅️ KRITIČNO!

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL not found! Check your .env file.\n"
        "Expected format: DATABASE_URL=postgresql://user:pass@host:port/dbname"
    )

print(f"✅ DATABASE_URL loaded: {DATABASE_URL[:30]}...")  # Debug print

engine = create_engine(DATABASE_URL)


def migrate():
    print("🚀 Starting migration...")

    with engine.connect() as conn:
        # 1. Enable extension
        print("📦 Enabling PGVector extension...")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("✅ PGVector enabled")

        # 2. Create table
        print("🗄️  Creating semantic_cache table...")
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS semantic_cache (
                id VARCHAR PRIMARY KEY,
                query_text TEXT,
                query_embedding vector(768),
                category VARCHAR,
                destination VARCHAR,
                results TEXT,
                result_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                use_count INTEGER DEFAULT 0,
                avg_rating INTEGER,
                freshness_days INTEGER
            )
        """
            )
        )
        print("✅ Table created")

        # 3. Create indexes
        print("🔍 Creating indexes...")

        # Regular indexes first
        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_semantic_cache_category
            ON semantic_cache(category)
        """
            )
        )
        print("  ✅ Category index")

        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_semantic_cache_destination
            ON semantic_cache(destination)
        """
            )
        )
        print("  ✅ Destination index")

        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_semantic_cache_created
            ON semantic_cache(created_at)
        """
            )
        )
        print("  ✅ Created_at index")

        # Vector index (needs data to build properly)
        try:
            conn.execute(
                text(
                    """
                CREATE INDEX IF NOT EXISTS semantic_cache_embedding_idx
                ON semantic_cache
                USING ivfflat (query_embedding vector_cosine_ops)
                WITH (lists = 100)
            """
                )
            )
            print("  ✅ Vector index (IVFFlat)")
        except Exception as e:
            print(f"  ⚠️  Vector index skipped (will auto-create after 10k rows): {e}")

        conn.commit()

    print("\n🎉 Migration completed successfully!")
