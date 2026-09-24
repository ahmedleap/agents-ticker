#!/usr/bin/env python3
"""
Bootstrap script to load symbols from overlap.txt and populate the instruments table.

Usage:
    python -m app.bootstrap_instruments
"""

import logging
import sys
from pathlib import Path

from app.config import settings
from app.database import db_manager
from app.models import Instrument
from app.services.alpaca_service import AlpacaService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_symbols_from_file(filepath: str) -> list:
    """
    Load symbol list from overlap.txt.
    
    Args:
        filepath: Path to symbol file
        
    Returns:
        List of unique symbols
    """
    symbols = []
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                # Skip header lines and empty lines
                if (
                    line
                    and not line.startswith("OVERLAPPING")
                    and not line.startswith("Generated")
                    and not line.startswith("Total")
                    and not line.startswith("=")
                    and len(line) <= 10  # Symbol sanity check
                ):
                    symbols.append(line.upper())

        # Remove duplicates and sort
        symbols = sorted(list(set(symbols)))
        logger.info(f"Loaded {len(symbols)} unique symbols from {filepath}")
        return symbols

    except FileNotFoundError:
        logger.error(f"Symbol file not found: {filepath}")
        return []
    except Exception as e:
        logger.error(f"Error loading symbols: {e}")
        return []


def bootstrap_instruments(symbols: list) -> dict:
    """
    Create instrument records for all symbols.
    
    Args:
        symbols: List of ticker symbols
        
    Returns:
        Dictionary with results
    """
    result = {
        "total_symbols": len(symbols),
        "created": 0,
        "already_exist": 0,
        "invalid": [],
        "errors": [],
    }

    if not symbols:
        logger.warning("No symbols to bootstrap")
        return result

    logger.info(f"Bootstrapping {len(symbols)} instruments")

    alpaca = AlpacaService()
    valid_symbols = []

    # Validate symbols by attempting a quote fetch
    logger.info("Validating symbols with Alpaca API...")
    batch_size = 100
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        try:
            quotes = alpaca.get_latest_quotes(batch)
            valid_symbols.extend(quotes.keys())
        except Exception as e:
            logger.warning(f"Error validating batch {i // batch_size + 1}: {e}")

    invalid_symbols = set(symbols) - set(valid_symbols)
    if invalid_symbols:
        logger.warning(f"Invalid symbols (no Alpaca data): {sorted(invalid_symbols)}")
        result["invalid"] = sorted(invalid_symbols)

    # Create instrument records for valid symbols
    with db_manager.session_scope() as session:
        for symbol in valid_symbols:
            try:
                # Check if already exists
                existing = session.query(Instrument).filter_by(ticker=symbol).first()
                if existing:
                    logger.debug(f"Instrument already exists: {symbol}")
                    result["already_exist"] += 1
                    continue

                # Create new instrument
                instrument = Instrument(
                    ticker=symbol,
                    name=symbol,  # Can be enhanced later with company name
                    asset_class="STOCK",
                )
                session.add(instrument)
                result["created"] += 1
                logger.debug(f"Created instrument: {symbol}")

            except Exception as e:
                logger.error(f"Error creating instrument for {symbol}: {e}")
                result["errors"].append(f"{symbol}: {str(e)}")

        try:
            session.commit()
            logger.info(f"Committed {result['created']} new instruments")
        except Exception as e:
            logger.error(f"Error committing instruments: {e}")
            result["errors"].append(f"Commit error: {str(e)}")

    logger.info(
        f"Bootstrap complete: {result['created']} created, "
        f"{result['already_exist']} already exist, "
        f"{len(result['invalid'])} invalid"
    )

    return result


def main():
    """Main entry point."""
    try:
        logger.info("=== Instruments Bootstrap ===")

        # Initialize database
        if not db_manager.initialize():
            logger.error("Failed to initialize database")
            return 1

        logger.info("Database initialized successfully")

        # Load symbols from overlap.txt
        symbol_file = Path(__file__).parent.parent / "overlap.txt"
        symbols = load_symbols_from_file(str(symbol_file))

        if not symbols:
            logger.error("No symbols loaded")
            return 1

        # Bootstrap instruments
        result = bootstrap_instruments(symbols)

        logger.info("=== Bootstrap Results ===")
        logger.info(f"Total symbols: {result['total_symbols']}")
        logger.info(f"Created: {result['created']}")
        logger.info(f"Already exist: {result['already_exist']}")
        logger.info(f"Invalid: {len(result['invalid'])}")

        if result["invalid"]:
            logger.warning(f"Invalid symbols: {result['invalid'][:10]}")  # Log first 10

        if result["errors"]:
            logger.error(f"Errors: {result['errors']}")
            return 1

        logger.info("Bootstrap completed successfully!")
        return 0

    except Exception as e:
        logger.error(f"Bootstrap failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
