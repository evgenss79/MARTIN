"""
Bootstrap module for MARTIN.

Initializes all components and starts the application.
"""

import asyncio
import os
import sys
from pathlib import Path

from src.common.config import init_config, get_config
from src.common.logging import setup_logging, get_logger
from src.adapters.storage import init_database

logger = get_logger(__name__)


def load_environment() -> None:
    """
    Load environment variables from .env file.
    
    Uses python-dotenv if available. Falls back gracefully if:
    - python-dotenv is not installed
    - .env file does not exist
    
    Note: Secret values are never logged.
    """
    # Look for .env in project root
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"
    
    if not env_file.exists():
        logger.info("No .env file found, using environment variables")
        return
    
    # Try to load .env using python-dotenv (graceful fallback if not installed)
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        logger.info("Loaded environment from .env file")
    except ImportError:
        # python-dotenv not installed - attempt manual loading
        logger.warning(
            "python-dotenv not installed, attempting manual .env loading. "
            "Install with: pip install python-dotenv"
        )
        try:
            _load_env_file_manual(env_file)
            logger.info("Loaded environment from .env file (manual)")
        except Exception as e:
            logger.warning(f"Failed to load .env manually: {e}")


def _load_env_file_manual(env_file: Path) -> None:
    """
    Manually load a .env file without python-dotenv.
    
    Simple parser that handles:
    - KEY=value
    - KEY="quoted value"
    - KEY='quoted value'
    - # comments
    - Empty lines
    
    Does NOT handle:
    - Multiline values
    - Variable expansion
    """
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            # Parse KEY=value
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove surrounding quotes if present
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                # Only set if not already in environment
                if key and key not in os.environ:
                    os.environ[key] = value


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
