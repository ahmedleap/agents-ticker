"""Price service for fetching, transforming, and persisting market data."""
import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session

from app.models import Instrument
from app.services.alpaca_service import AlpacaService, AlpacaMarketDataError, AlpacaTimeoutError
from app.database import db_manager

logger = logging.getLogger(__name__)


class PriceService:
    """Service for managing market prices and data persistence."""

    def __init__(self, alpaca_service: AlpacaService):
        self.alpaca = alpaca_service
        self.last_successful_fetch: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.total_fetches: int = 0
        self.successful_fetches: int = 0
        self.failed_fetches: int = 0
        self.total_prices_inserted: int = 0

    def get_or_create_instrument(self, session: Session, symbol: str) -> Instrument:
        """
        Get existing instrument or create a new one.
        
        Args:
            session: Database session
            symbol: Ticker symbol
            
        Returns:
            Instrument object
        """
        instrument = session.query(Instrument).filter_by(ticker=symbol).first()
        
        if not instrument:
            logger.info(f"Creating new instrument record for {symbol}")
            instrument = Instrument(
                ticker=symbol,
                name=symbol,  # Use symbol as placeholder; could be enhanced
                asset_class="STOCK",
            )
            session.add(instrument)
            session.flush()  # Get the ID without committing
        
        return instrument

    def persist_price(
        self,
        session: Session,
        symbol: str,
        bid_price: float,
        ask_price: float,
        timestamp: datetime,
    ) -> bool:
        """
        Update instrument with latest bid/ask prices.
        
        Args:
            session: Database session
            symbol: Ticker symbol
            bid_price: Bid price
            ask_price: Ask price
            timestamp: Quote timestamp
            
        Returns:
            True if successful, False otherwise
        """
        try:
            instrument = self.get_or_create_instrument(session, symbol)
            
            # Update bid/ask directly on instrument (mid_price is computed by database)
            instrument.bid = Decimal(str(bid_price))
            instrument.ask = Decimal(str(ask_price))
            instrument.price_updated_at = timestamp
            
            session.add(instrument)
            logger.debug(
                f"Queued price update: {symbol} "
                f"bid={bid_price} ask={ask_price} at={timestamp}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error persisting price for {symbol}: {e}")
            return False

    def fetch_and_persist_prices(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Fetch prices from Alpaca and persist to database.
        
        Args:
            symbols: List of ticker symbols to fetch
            
        Returns:
            Dictionary with fetch results and statistics
        """
        result = {
            "success": False,
            "timestamp": datetime.utcnow(),
            "symbols_requested": len(symbols),
            "prices_inserted": 0,
            "errors": [],
        }
        
        self.total_fetches += 1
        
        logger.info(f"Starting price fetch for {len(symbols)} symbols: {symbols}")
        
        try:
            # Fetch quotes from Alpaca
            quotes = self.alpaca.get_latest_quotes(symbols)
            
            if not quotes:
                logger.warning("No quotes returned from Alpaca")
                result["errors"].append("No quotes from Alpaca API")
                self.failed_fetches += 1
                self.last_error = "No quotes from Alpaca"
                return result
            
            # Parse and persist prices
            prices_to_insert = []
            
            for symbol in symbols:
                if symbol not in quotes:
                    logger.warning(f"No quote data for {symbol}")
                    continue
                
                quote_data = quotes[symbol]
                parsed_quote = self.alpaca.parse_quote(symbol, quote_data)
                
                if not parsed_quote:
                    logger.warning(f"Failed to parse quote for {symbol}")
                    continue
                
                bid = parsed_quote.get("bid")
                ask = parsed_quote.get("ask")
                timestamp_str = parsed_quote.get("timestamp")
                
                if bid is None or ask is None:
                    logger.warning(f"Missing bid/ask for {symbol}: bid={bid}, ask={ask}")
                    continue
                
                # Validate bid/ask prices
                if ask <= 0 or bid <= 0:
                    logger.warning(f"Invalid prices for {symbol}: bid={bid}, ask={ask} (must be > 0)")
                    continue
                
                if ask < bid:
                    logger.warning(f"Invalid prices for {symbol}: ask={ask} < bid={bid}")
                    continue
                
                # Parse timestamp
                try:
                    if isinstance(timestamp_str, str):
                        # Try ISO format first
                        try:
                            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            timestamp = datetime.utcnow()
                    else:
                        timestamp = datetime.utcnow()
                except Exception as e:
                    logger.warning(f"Error parsing timestamp for {symbol}: {e}")
                    timestamp = datetime.utcnow()
                
                prices_to_insert.append({
                    "symbol": symbol,
                    "bid": bid,
                    "ask": ask,
                    "timestamp": timestamp,
                })
            
            # Persist all prices in a single transaction
            if prices_to_insert:
                with db_manager.session_scope() as session:
                    inserted_count = 0
                    for price_data in prices_to_insert:
                        if self.persist_price(
                            session,
                            price_data["symbol"],
                            price_data["bid"],
                            price_data["ask"],
                            price_data["timestamp"],
                        ):
                            inserted_count += 1
                    
                    session.commit()
                    
                result["prices_inserted"] = inserted_count
                self.total_prices_inserted += inserted_count
                
                logger.info(
                    f"Successfully inserted {inserted_count} prices into database"
                )
            else:
                logger.warning("No prices parsed from Alpaca response")
                result["errors"].append("No valid prices from Alpaca")
            
            result["success"] = result["prices_inserted"] > 0
            
            if result["success"]:
                self.successful_fetches += 1
                self.last_successful_fetch = result["timestamp"]
                self.last_error = None
            else:
                self.failed_fetches += 1
            
            return result
            
        except AlpacaTimeoutError as e:
            logger.error(f"Alpaca timeout during fetch: {e}")
            result["errors"].append(f"Alpaca timeout: {str(e)}")
            self.failed_fetches += 1
            self.last_error = str(e)
            return result
            
        except AlpacaMarketDataError as e:
            logger.error(f"Alpaca API error: {e}")
            result["errors"].append(f"Alpaca error: {str(e)}")
            self.failed_fetches += 1
            self.last_error = str(e)
            return result
            
        except Exception as e:
            logger.error(f"Unexpected error during price fetch: {e}", exc_info=True)
            result["errors"].append(f"Unexpected error: {str(e)}")
            self.failed_fetches += 1
            self.last_error = str(e)
            return result

    def get_latest_price(self, symbol: str) -> Optional[dict]:
        """
        Get the latest price for a symbol from the instruments table.
        
        Args:
            symbol: Ticker symbol
            
        Returns:
            Latest price data or None if not found
        """
        try:
            with db_manager.session_scope() as session:
                instrument = session.query(Instrument).filter(
                    Instrument.ticker == symbol.upper()
                ).first()
                
                if instrument and instrument.bid and instrument.ask:
                    mid = (float(instrument.bid) + float(instrument.ask)) / 2 if instrument.bid and instrument.ask else None
                    return {
                        "symbol": symbol,
                        "bid": float(instrument.bid),
                        "ask": float(instrument.ask),
                        "mid_price": mid,
                        "price_updated_at": instrument.price_updated_at.isoformat() if instrument.price_updated_at else None,
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"Error fetching latest price for {symbol}: {e}")
            return None

    def get_status(self) -> dict:
        """Get service status and statistics."""
        return {
            "last_successful_fetch": self.last_successful_fetch.isoformat() if self.last_successful_fetch else None,
            "last_error": self.last_error,
            "total_fetches": self.total_fetches,
            "successful_fetches": self.successful_fetches,
            "failed_fetches": self.failed_fetches,
            "total_prices_inserted": self.total_prices_inserted,
            "success_rate": (
                self.successful_fetches / self.total_fetches * 100
                if self.total_fetches > 0
                else 0
            ),
        }

    def fetch_and_persist_prices_batch(
        self,
        symbols: List[str],
        num_workers: int = 5,
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """
        Fetch prices for multiple symbols using threading (Job 1).
        
        Batches symbols into groups and uses ThreadPoolExecutor for parallel API calls.
        
        Args:
            symbols: List of all ticker symbols to fetch
            num_workers: Number of worker threads
            batch_size: Symbols per API request (Alpaca allows up to 100)
            
        Returns:
            Dictionary with aggregated results from all batches
        """
        result = {
            "success": False,
            "timestamp": datetime.utcnow(),
            "total_symbols": len(symbols),
            "prices_inserted": 0,
            "batches_processed": 0,
            "batches_failed": 0,
            "errors": [],
        }

        if not symbols:
            logger.warning("No symbols provided for batch price fetch")
            return result

        # Split symbols into batches
        batches = [
            symbols[i:i + batch_size]
            for i in range(0, len(symbols), batch_size)
        ]

        logger.info(
            f"Starting batch price fetch: {len(symbols)} symbols in {len(batches)} batches, "
            f"{num_workers} workers"
        )

        total_inserted = 0
        batches_failed = 0

        # Use ThreadPoolExecutor for parallel batch processing
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # Submit all batch jobs
            future_to_batch = {
                executor.submit(self.fetch_and_persist_prices, batch): i
                for i, batch in enumerate(batches)
            }

            # Process completed batches
            for future in as_completed(future_to_batch):
                batch_idx = future_to_batch[future]
                try:
                    batch_result = future.result()
                    total_inserted += batch_result.get("prices_inserted", 0)

                    if batch_result.get("success"):
                        logger.info(
                            f"Batch {batch_idx + 1}/{len(batches)}: "
                            f"Inserted {batch_result['prices_inserted']} prices"
                        )
                    else:
                        batches_failed += 1
                        if batch_result.get("errors"):
                            result["errors"].extend(batch_result["errors"])
                except Exception as e:
                    logger.error(f"Error processing batch {batch_idx + 1}: {e}")
                    batches_failed += 1
                    result["errors"].append(f"Batch {batch_idx + 1} exception: {str(e)}")

        result["prices_inserted"] = total_inserted
        result["batches_processed"] = len(batches) - batches_failed
        result["batches_failed"] = batches_failed
        result["success"] = total_inserted > 0

        logger.info(
            f"Batch price fetch completed: "
            f"{result['prices_inserted']} prices inserted from {result['batches_processed']} batches"
        )

        if result["success"]:
            self.successful_fetches += 1
            self.last_successful_fetch = result["timestamp"]
            self.last_error = None
        else:
            self.failed_fetches += 1

        return result
