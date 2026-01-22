"""
Bootstrap module for MARTIN.

Initializes all components and starts the application.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.common.config import init_config, get_config
from src.common.logging import setup_logging, get_logger
from src.adapters.storage import init_database

logger = get_logger(__name__)


def load_environment() -> None:
    """Load environment variables from .env file."""
    # Look for .env in project root
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"
    
    if env_file.exists():
        load_dotenv(env_file)
        logger.info("Loaded environment from .env file")
    else:
        logger.info("No .env file found, using environment variables")


def initialize() -> None:
    """
    Initialize all application components.
    
    This function should be called once at startup.
    """
    # Load environment first
    load_environment()
    
    # Initialize configuration
    config = init_config()
    
    # Setup logging
    setup_logging(
        level=config.app.get("log_level", "INFO"),
        format_type=config.app.get("log_format", "json")
    )
    
    logger.info("Configuration loaded", 
                timezone=config.app.get("timezone"),
                execution_mode=config.execution.get("mode"),
                assets=config.trading.get("assets"))
    
    # Initialize database
    dsn = config.storage.get("dsn", "sqlite:///data/martin.db")
    init_database(dsn)
    logger.info("Database initialized", dsn=dsn)
    
    logger.info("MARTIN bootstrap complete")


async def shutdown() -> None:
    """
    Gracefully shutdown all components.
    """
    logger.info("Shutting down MARTIN...")
    
    # Close database connection
    from src.adapters.storage import get_database
    try:
        db = get_database()
        db.close()
        logger.info("Database connection closed")
    except Exception:
        pass
    
    logger.info("MARTIN shutdown complete")
