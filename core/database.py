"""
Database configuration and session management.
"""
import os
import uuid
from sqlalchemy import create_engine, Column, String, JSON, DateTime, Text, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session as DBSession
from datetime import datetime
from dotenv import load_dotenv
from .logger import get_logger

load_dotenv()
logger = get_logger(__name__)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    
    created_at = Column(DateTime, default=datetime.utcnow)

class GeocodingCache(Base):
    """Cache for geocoding results."""
    __tablename__ = "geocoding_cache"
    
    query = Column(String, primary_key=True, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    status = Column(String)  # "exact", "neighborhood", "failed"
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    """Create all tables."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")

def get_db():
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
