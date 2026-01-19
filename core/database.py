"""
Database configuration and session management.
"""

import os
import uuid
from datetime import UTC, datetime

from dotenv import load_dotenv
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .logger import get_logger

# Import logger
try:
    from .logger import get_logger

    logger = get_logger(__name__)
except Exception:
    import logging

    logger = logging.getLogger(__name__)

load_dotenv()

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/travel_companion")

# Create engine
engine = create_engine(DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


# Database Models
class ChatSession(Base):
    """Chat session model."""

    __tablename__ = "chat_sessions"

    session_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=True)
    data = Column(JSON)  # Chat History
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class Trip(Base):
    """Structured Trip Data for Analytics."""

    __tablename__ = "trips"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("chat_sessions.session_id"), index=True)

    # Structured Fields for Querying
    destination = Column(String, index=True)
    duration = Column(String)
    budget = Column(String)
    interests = Column(String)

    # The Full Result
    itinerary_text = Column(Text)

    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class GeocodingCache(Base):
    """Cache for geocoding results."""

    __tablename__ = "geocoding_cache"

    query = Column(String, primary_key=True, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    status = Column(String)  # "exact", "neighborhood", "failed"
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class SemanticCache(Base):
    """Cache for research results with vector embeddings."""

    __tablename__ = "semantic_cache"

    id = Column(String, primary_key=True)

    # Query Info
    query_text = Column(Text, index=True)
    query_embedding = Column(Vector(None))  # Changed from Vector(768)

    # Categorization
    category = Column(String, index=True)
    destination = Column(String, index=True)

    # Cached Results (JSON)
    results = Column(Text)
    result_count = Column(Float)

    # Metadata
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
    last_used = Column(DateTime, default=lambda: datetime.now(UTC))
    use_count = Column(Float, default=0)

    # Quality Metrics
    avg_rating = Column(Float)
    freshness_days = Column(Float)


def enable_pgvector():
    """Enable PGVector extension in PostgreSQL."""
    from sqlalchemy import text

    logger.info("Enabling PGVector extension...")

    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            logger.info("PGVector extension enabled")
        except Exception as e:
            logger.error(f"Failed to enable PGVector: {e}")
            raise


def init_db():
    """Create all tables and enable PGVector."""
    logger.info("Initializing database...")

    # 1. Enable PGVector first
    enable_pgvector()

    # 2. Create all tables
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")

    # 3. List created tables
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logger.info(f"Tables in database: {', '.join(tables)}")

    # 4. Create vector indexes (optional, only if table exists)
    try:
        create_vector_indexes()
    except Exception as e:
        logger.warning(f"Vector index creation skipped: {e}")
        logger.info("Vector indexes will be created after first cache entries")


def get_db():
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_vector_indexes():
    """Create IVFFlat index on embeddings for fast similarity search."""
    from sqlalchemy import text

    logger.info("Creating vector indexes...")

    with engine.connect() as conn:
        # Check if table exists first
        table_exists = conn.execute(
            text(
                """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'semantic_cache'
            )
        """
            )
        ).scalar()

        if not table_exists:
            logger.warning("semantic_cache table doesn't exist yet, skipping index creation")
            return

        # Check if table has data (IVFFlat needs some rows)
        row_count = conn.execute(text("SELECT COUNT(*) FROM semantic_cache")).scalar()

        if row_count < 100:
            logger.info(f"Only {row_count} rows in cache. Vector index will be created after 100+ entries.")
            return

        try:
            # IVFFlat index (faster than exact search, good for >10k vectors)
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
            conn.commit()
            logger.info("Vector indexes created")
        except Exception as e:
            logger.warning(f"Index creation failed: {e}")
            logger.info("This is OK - index will be created when you have more data")
