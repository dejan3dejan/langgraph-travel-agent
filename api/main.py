"""
Main FastAPI application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .chat import router as chat_router
from core.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="AI Travel Companion API",
    version="0.2.0",
    description="Conversational AI for personalized travel planning"
)

# CORS (for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include chat router
app.include_router(chat_router, prefix="/api/v1", tags=["chat"])


class HealthCheck(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "0.2.0"


@app.get("/")
async def root():
    """Root endpoint."""
    logger.info("Root endpoint called")
    return {
        "message": "AI Travel Companion API",
        "version": "0.2.0",
        "docs": "/docs"
    }


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint."""
    return HealthCheck(status="healthy", version="0.2.0")
