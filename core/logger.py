"""
Structured logging configuration for Travel Companion.
"""
from loguru import logger
import sys
from pathlib import Path

# Remove default handler
logger.remove()

# Add console handler with custom format
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)

# Add file handler for production logs
log_file = Path("logs/travel_companion.log")
log_file.parent.mkdir(exist_ok=True)

logger.add(
    log_file,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="1 week"
)

# Create logger instance for import
travel_logger = logger

def get_logger(name: str):
    """Get logger instance for specific module."""
    return logger.bind(module=name)