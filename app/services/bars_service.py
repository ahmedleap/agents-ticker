"""Bars service for historical price data management."""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models import Instrument, InstrumentPriceHistory
from app.services.alpaca_service import AlpacaService, AlpacaMarketDataError
from app.database import db_manager

logger = logging.getLogger(__name__)


class BarsService:
    """Service for managing historical OHLC price data."""

    def __init__(self, alpaca_service: AlpacaService):
        self.alpaca = alpaca_service
        self.invalid_symbols: List[str] = []

    def persist_bar(
        self,
        session: Session,
        instrument_id: str,
        timestamp: datetime,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: int,
    ) -> bool:
        """
        Insert a single OHLC bar into the database.
        
        Args:
            session: Database session
            instrument_id: UUID of the instrument
            timestamp: Bar timestamp
            open_price: Opening price
            high: High price
            low: Low price
            close: Closing price
            volume: Volume
            
        Returns:
            True if successful, False otherwise
        """
        try:
            price_history = InstrumentPriceHistory(
                instrument_id=instrument_id,
                timestamp=timestamp,
                open=Decimal(str(open_price)),
                high=Decimal(str(high)),
                low=Decimal(str(low)),
                close=Decimal(str(close)),
                volume=volume,
            )
            session.add(price_history)
            return True
        except Exception as e:
            logger.error(f"Error persisting bar for {instrument_id}: {e}")
            return False

    def load_historical_bars(
        self,
        symbol: str,
        days: int = 365,
    ) -> Dict[str, Any]:
        """
        Fetch and persist historical bars for a single symbol (cold start).
        
        Args:
            symbol: Ticker symbol
            days: Number of days of historical data to fetch
            
        Returns:
            Dictionary with results: {success, bars_inserted, errors}
        """
        result = {
            "symbol": symbol,
            "success": False,
            "bars_inserted": 0,
            "errors": [],
        }

        try:
            # Calculate date range (exclude last 15 minutes for Basic plan)
            now_utc = datetime.utcnow()
            end_date = (now_utc - timedelta(minutes=15)).date()
            start_date = end_date - timedelta(days=days)

            logger.info(f"Loading {days} days of bars for {symbol} ({start_date} to {end_date})")

            # Get instrument
            with db_manager.session_scope() as session:
                instrument = session.query(Instrument).filter_by(ticker=symbol).first()
                if not instrument:
                    msg = f"Instrument not found for symbol {symbol}"
                    logger.warning(msg)
                    result["errors"].append(msg)
                    self.invalid_symbols.append(symbol)
                    return result

                instrument_id = instrument.instrument_id

            # Fetch bars from Alpaca
            try:
                bars = self.alpaca.get_bars(
                    symbol,
                    start_date.isoformat(),
                    end_date.isoformat(),
                )
            except AlpacaMarketDataError as e:
                msg = f"Alpaca API error for {symbol}: {e}"
                logger.error(msg)
                result["errors"].append(msg)
                self.invalid_symbols.append(symbol)
                return result

            if not bars:
                msg = f"No bars returned from Alpaca for {symbol}"
                logger.warning(msg)
                result["errors"].append(msg)
                return result

            # Persist bars in batch
            with db_manager.session_scope() as session:
                inserted_count = 0
                for bar in bars:
                    try:
                        timestamp = datetime.fromisoformat(
                            bar.get("t", "").replace("Z", "+00:00")
                        )
                        
                        if self.persist_bar(
                            session,
                            instrument_id,
                            timestamp,
                            float(bar.get("o", 0)),
                            float(bar.get("h", 0)),
                            float(bar.get("l", 0)),
                            float(bar.get("c", 0)),
                            int(bar.get("v", 0)),
                        ):
                            inserted_count += 1
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Failed to parse bar for {symbol}: {e}")
                        continue

                session.commit()
                result["bars_inserted"] = inserted_count
                result["success"] = inserted_count > 0

                logger.info(f"Inserted {inserted_count} bars for {symbol}")

            return result

        except Exception as e:
            logger.error(f"Unexpected error loading bars for {symbol}: {e}", exc_info=True)
            result["errors"].append(f"Unexpected error: {str(e)}")
            self.invalid_symbols.append(symbol)
            return result

    def load_eod_bar(self, symbol: str, days_back: int = 1) -> Dict[str, Any]:
        """
        Fetch and persist the EOD bar for a symbol (runs daily).
        
        Args:
            symbol: Ticker symbol
            days_back: How many days back to fetch (default: 1 for previous day)
            
        Returns:
            Dictionary with results
        """
        result = {
            "symbol": symbol,
            "success": False,
            "errors": [],
        }

        try:
            # Calculate date range for previous trading day
            # Account for 15-minute delay requirement
            now_utc = datetime.utcnow()
            end_date = (now_utc - timedelta(minutes=15)).date()
            start_date = end_date - timedelta(days=days_back)

            logger.info(f"Loading EOD bar for {symbol} ({start_date} to {end_date})")

            # Get instrument
            with db_manager.session_scope() as session:
                instrument = session.query(Instrument).filter_by(ticker=symbol).first()
                if not instrument:
                    msg = f"Instrument not found for symbol {symbol}"
                    logger.warning(msg)
                    result["errors"].append(msg)
                    return result

                instrument_id = instrument.instrument_id

            # Fetch bar from Alpaca
            try:
                bars = self.alpaca.get_bars(
                    symbol,
                    start_date.isoformat(),
                    end_date.isoformat(),
                )
            except AlpacaMarketDataError as e:
                msg = f"Alpaca API error for {symbol}: {e}"
                logger.error(msg)
                result["errors"].append(msg)
                return result

            if not bars:
                msg = f"No bars returned from Alpaca for {symbol}"
                logger.warning(msg)
                result["errors"].append(msg)
                return result

            # Use the last bar (EOD)
            bar = bars[-1]

            # Persist the bar
            with db_manager.session_scope() as session:
                timestamp = datetime.fromisoformat(
                    bar.get("t", "").replace("Z", "+00:00")
                )

                if self.persist_bar(
                    session,
                    instrument_id,
                    timestamp,
                    float(bar.get("o", 0)),
                    float(bar.get("h", 0)),
                    float(bar.get("l", 0)),
                    float(bar.get("c", 0)),
                    int(bar.get("v", 0)),
                ):
                    session.commit()
                    result["success"] = True
                    logger.info(f"Inserted EOD bar for {symbol}")
                else:
                    result["errors"].append(f"Failed to persist bar for {symbol}")

            return result

        except Exception as e:
            logger.error(f"Unexpected error loading EOD bar for {symbol}: {e}", exc_info=True)
            result["errors"].append(f"Unexpected error: {str(e)}")
            return result

    def get_invalid_symbols(self) -> List[str]:
        """Get list of symbols that failed to load."""
        return self.invalid_symbols
