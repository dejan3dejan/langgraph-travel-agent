"""Database configuration, models, and session management."""

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from .logger import get_logger

logger = get_logger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/travel_companion")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    preferences = relationship("UserPreference", back_populates="user", uselist=False)
    sessions = relationship("ChatSession", back_populates="user")
    trips = relationship("Trip", back_populates="user")
    auth_tokens = relationship("AuthToken", back_populates="user", cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    default_budget = Column(String, default="Medium")
    default_interests = Column(String, default="General Sightseeing")
    num_travelers = Column(Integer, default=1)
    age_range = Column(String, default="adults")
    trip_type = Column(String, nullable=True)
    start_location = Column(String, nullable=True)
    constraints = Column(String, nullable=True)  # legacy free-text; superseded by travel_constraints
    travel_constraints = Column(JSON, nullable=True)  # {hard: [...], soft: [...]}
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="preferences")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), index=True, nullable=True)
    title = Column(String, default="New Chat")
    data = Column(JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="sessions")
    trips = relationship("Trip", back_populates="session")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("chat_sessions.session_id"), index=True)
    user_id = Column(String, ForeignKey("users.id"), index=True, nullable=True)
    destination = Column(String, index=True)
    duration = Column(String)
    budget = Column(String)
    interests = Column(String)
    itinerary_text = Column(Text)
    geo = Column(JSON, nullable=True)  # {hotel, days[]} map payload; null for text-only/legacy trips
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="trips")
    session = relationship("ChatSession", back_populates="trips")
    members = relationship("TripMember", back_populates="trip", cascade="all, delete-orphan")


class TripMember(Base):
    __tablename__ = "trip_members"

    # Collaborators on a trip. The owner stays on Trip.user_id and is not a member row; this table
    # holds invited users with a viewer (read) or editor (read + edit) role. Session access is
    # derived from membership of the trip that owns the session.
    __table_args__ = (
        UniqueConstraint("trip_id", "user_id", name="uq_trip_member"),
        CheckConstraint("role IN ('viewer', 'editor')", name="ck_trip_member_role"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    trip_id = Column(String, ForeignKey("trips.id"), index=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), index=True, nullable=False)
    role = Column(String, nullable=False, default="viewer")
    invited_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    trip = relationship("Trip", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])


class SharedItinerary(Base):
    __tablename__ = "shared_itineraries"

    # Public snapshot of a delivered plan. No user_id/session by design: a share link must not
    # reveal who made it or their saved constraints.
    id = Column(String, primary_key=True)  # secrets.token_urlsafe; unguessable is the access control
    title = Column(String)
    itinerary_text = Column(Text, nullable=False)
    geo = Column(JSON, nullable=True)  # {hotel, days[]} map payload; null for text-only snapshots
    revoke_token = Column(String, nullable=True)  # owner secret; required to delete the snapshot
    expires_at = Column(DateTime, nullable=True)  # past this the public GET 404s; null never expires
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    # Single-use, expiring tokens for email verification and password reset. Only the SHA-256 hash
    # of the raw token is stored (see core/tokens.py); the raw value lives only in the email link.
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    purpose = Column(String, nullable=False)  # "email_verify" | "password_reset"
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)  # set when consumed; enforces single use
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="auth_tokens")


class Feedback(Base):
    __tablename__ = "feedback"

    # One table backs every feedback context. kind says which: 'plan' (rate a delivered itinerary),
    # 'compare' (why one A/B variant over the other), or 'app' (general feedback / bug report).
    # Both rating and message are optional, but a row must carry at least one (DB check below).
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kind = Column(String, nullable=False)
    rating = Column(Integer, nullable=True)  # 1-5 stars when given
    message = Column(Text, nullable=True)
    session_id = Column(String, ForeignKey("chat_sessions.session_id"), index=True, nullable=True)
    user_id = Column(String, ForeignKey("users.id"), index=True, nullable=True)
    context = Column(JSON, nullable=True)  # kind-specific extras, e.g. {"chosen": "B"} for compare
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        CheckConstraint("kind in ('plan', 'compare', 'app')", name="feedback_kind_valid"),
        CheckConstraint("rating is null or (rating >= 1 and rating <= 5)", name="feedback_rating_range"),
        CheckConstraint("rating is not null or message is not null", name="feedback_has_content"),
    )


class GeocodingCache(Base):
    __tablename__ = "geocoding_cache"

    query = Column(String, primary_key=True, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    status = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class SemanticCache(Base):
    __tablename__ = "semantic_cache"

    id = Column(String, primary_key=True)
    query_text = Column(Text, index=True)
    query_embedding = Column(Vector(None))
    category = Column(String, index=True)
    destination = Column(String, index=True)
    results = Column(Text)
    result_count = Column(Float)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
    last_used = Column(DateTime, default=lambda: datetime.now(UTC))
    use_count = Column(Float, default=0)
    avg_rating = Column(Float)
    freshness_days = Column(Float)


def _run_migrations():
    """Bring the schema to the latest Alembic revision.

    The baseline migration creates the pgvector extension and all tables, so this
    replaces the old create_all() + manual CREATE EXTENSION. Idempotent, a no-op
    when already at head, which makes it safe to run on every startup.
    """
    from alembic import command
    from alembic.config import Config

    logger.info("Running database migrations...")
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    command.upgrade(Config(str(alembic_ini)), "head")
    logger.info("Migrations applied (schema at head)")


def init_db():
    """Migrate the database to head, then ensure vector indexes exist."""
    logger.info("Initializing database...")

    _run_migrations()

    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logger.info(f"Tables in database: {', '.join(tables)}")

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
    """Create IVFFlat index on semantic_cache embeddings for fast similarity search."""
    from sqlalchemy import text

    logger.info("Creating vector indexes...")

    with engine.connect() as conn:
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
