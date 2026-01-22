#!/usr/bin/env python3
"""
MARTIN Telegram Trading Bot - Main Entry Point

A Telegram bot that discovers Polymarket hourly "BTC Up or Down" and 
"ETH Up or Down" markets and provides trading signals with quality scoring.

Usage:
    python -m src.main
    
Or with the main script:
    python src/main.py
"""

import asyncio
import signal
import sys
from typing import NoReturn

from src.bootstrap import initialize, shutdown
from src.common.logging import get_logger


async def main() -> None:
    """
    Main application entry point.
    
    Initializes all components and starts the bot.
    """
    logger = get_logger(__name__)
    
    # Initialize application
    try:
        initialize()
    except Exception as e:
        print(f"Failed to initialize MARTIN: {e}", file=sys.stderr)
        sys.exit(1)
    
    logger.info("MARTIN started successfully")
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    def signal_handler(sig: signal.Signals) -> None:
        logger.info(f"Received signal {sig.name}, initiating shutdown...")
        asyncio.create_task(shutdown())
        loop.stop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler, sig)
    
    try:
        # Import and start services after initialization
        from src.services.orchestrator import Orchestrator
        from src.common.config import get_config
        
        config = get_config()
        orchestrator = Orchestrator(config)
        
        # Start the orchestrator
        await orchestrator.start()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error("Fatal error in main loop", error=str(e))
        raise
    finally:
        await shutdown()


def run() -> NoReturn:
    """Run the application."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    run()
