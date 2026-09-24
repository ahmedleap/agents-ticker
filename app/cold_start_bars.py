#!/usr/bin/env python3
"""
Cold start script to load 365 days of historical bars for all symbols (Job 2).

This is a manual one-time job to backload historical price data.

Usage:
    python -m app.cold_start_bars
"""

import logging
import sys
from datetime import datetime

from app.config import settings
from app.database import db_manager
from app.models import Instrument
from app.services.alpaca_service import AlpacaService
from app.services.bars_service import BarsService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def cold_start_bars(days: int = 365) -> dict:
    """
    Load historical bars for all instruments.
    
    Args:
        days: Number of days of historical data to load
        
    Returns:
        Dictionary with results
    """
    result = {
        "total_symbols": 0,
        "successful": 0,
        "failed": 0,
        "bars_inserted": 0,
        "invalid_symbols": [],
        "errors": [],
        "start_time": datetime.utcnow(),
    }

    try:
        # Get all instruments
        with db_manager.session_scope() as session:
            instruments = session.query(Instrument).order_by(Instrument.ticker).all()
            symbols = [(i.instrument_id, i.ticker) for i in instruments]
            result["total_symbols"] = len(symbols)

        if not symbols:
            logger.warning("No instruments found to load")
            return result

        logger.info(f"Loading {days} days of bars for {len(symbols)} symbols")

        # Initialize services
        alpaca_service = AlpacaService()
        bars_service = BarsService(alpaca_service)

        # Process each symbol
        for idx, (instrument_id, symbol) in enumerate(symbols, 1):
            try:
                logger.info(f"[{idx}/{len(symbols)}] Loading bars for {symbol}")

                # Load bars for this symbol
                bar_result = bars_service.load_historical_bars(symbol, days)

                if bar_result["success"]:
                    result["successful"] += 1
                    result["bars_inserted"] += bar_result["bars_inserted"]
                    logger.info(
                        f"  ✓ {symbol}: {bar_result['bars_inserted']} bars inserted"
                    )
                else:
                    result["failed"] += 1
                    if bar_result["errors"]:
                        result["errors"].extend(bar_result["errors"])
                    logger.warning(f"  ✗ {symbol}: {bar_result.get('errors', 'Unknown error')}")

            except Exception as e:
                logger.error(f"Exception processing {symbol}: {e}", exc_info=True)
                result["failed"] += 1
                result["errors"].append(f"{symbol}: {str(e)}")

        # Get invalid symbols from bars service
        result["invalid_symbols"] = bars_service.get_invalid_symbols()

        result["end_time"] = datetime.utcnow()
        duration = (result["end_time"] - result["start_time"]).total_seconds()
        result["duration_seconds"] = duration

        return result

    except Exception as e:
        logger.error(f"Cold start failed: {e}", exc_info=True)
        result["errors"].append(f"Fatal error: {str(e)}")
        return result


def main():
    """Main entry point."""
    try:
        logger.info("=== Cold Start Bars Loading (Job 2) ===")

        # Initialize database
        if not db_manager.initialize():
            logger.error("Failed to initialize database")
            return 1

        logger.info("Database initialized successfully")

        # Run cold start
        result = cold_start_bars(days=365)

        # Print results
        logger.info("=== Cold Start Results ===")
        logger.info(f"Total symbols: {result['total_symbols']}")
        logger.info(f"Successful: {result['successful']}")
        logger.info(f"Failed: {result['failed']}")
        logger.info(f"Total bars inserted: {result['bars_inserted']}")
        logger.info(f"Duration: {result.get('duration_seconds', 0):.1f} seconds")

        if result["invalid_symbols"]:
            logger.warning(f"Invalid symbols: {result['invalid_symbols'][:10]}")

        if result["errors"]:
            logger.error("Errors encountered:")
            for error in result["errors"][:10]:  # Log first 10
                logger.error(f"  - {error}")

        if result["failed"] > 0:
            logger.warning(f"Cold start completed with {result['failed']} failures")
            return 1
        else:
            logger.info("Cold start completed successfully!")
            return 0

    except Exception as e:
        logger.error(f"Cold start failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
