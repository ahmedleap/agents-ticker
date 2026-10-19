"""Scheduled tasks for market data polling."""
import logging
from datetime import datetime, time
from typing import Optional, List
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job

from app.config import settings
from app.services.alpaca_service import AlpacaService
from app.services.price_service import PriceService
from app.services.bars_service import BarsService
from app.services.forex_service import ForexService
from app.database import db_manager
from app.models import Instrument

logger = logging.getLogger(__name__)


def is_market_open() -> bool:
    """
    Check if US stock market is currently open.
    Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday.
    
    Returns:
        True if market is open, False otherwise
    """
    et = pytz.timezone('America/New_York')
    now = datetime.now(et)
    
    # Market closed on weekends (5 = Saturday, 6 = Sunday)
    if now.weekday() >= 5:
        return False
    
    # Market hours: 9:30 AM - 4:00 PM ET
    market_open_time = time(9, 30)
    market_close_time = time(16, 0)
    
    return market_open_time <= now.time() < market_close_time


class SchedulerManager:
    """Manages scheduled polling of market data with threading support."""

    def __init__(
        self,
        price_service: PriceService,
        bars_service: BarsService,
        all_symbols: List[str],
        forex_service: Optional[ForexService] = None,
        crypto_symbols: Optional[List[str]] = None,
        eod_symbols: Optional[List[str]] = None,
    ):
        self.price_service = price_service
        self.bars_service = bars_service
        self.all_symbols = all_symbols
        self.eod_symbols = all_symbols if eod_symbols is None else eod_symbols
        self.forex_service = forex_service or ForexService()
        self.crypto_symbols = crypto_symbols or settings.crypto_symbols_list
        self.scheduler: Optional[BackgroundScheduler] = None
        self.poll_job: Optional[Job] = None
        self.forex_job: Optional[Job] = None
        self.crypto_job: Optional[Job] = None
        self.eod_job: Optional[Job] = None
        self.is_running = False

    def start(self) -> bool:
        """
        Start the scheduler with all jobs.
        
        Returns:
            True if scheduler started successfully, False otherwise
        """
        try:
            logger.info("Starting market data polling scheduler")
            
            self.scheduler = BackgroundScheduler()
            
            # Job 1: Real-time quote fetching every 10 seconds (aligned to clock seconds)
            # Runs only during market hours (9:30 AM - 4:00 PM ET, Mon-Fri)
            # Uses CronTrigger with second='0,10,20,30,40,50' for perfect alignment
            self.poll_job = self.scheduler.add_job(
                func=self._poll_market_data_threaded,
                trigger=CronTrigger(
                    second='0,10,20,30,40,50',
                    timezone='America/New_York'
                ),
                id="market_data_poll_job1",
                name="Job 1: Real-time Price Poll (10s aligned, market hours only)",
                replace_existing=True,
                max_instances=1,
                coalesce=True,  # Skip missed runs if scheduler is overloaded
            )
            
            logger.info(
                f"Job 1 scheduled: Every 10 seconds (0,10,20,30,40,50) during market hours, "
                f"{len(self.all_symbols)} symbols, 5 workers, 100 symbols/batch"
            )
            
            # Job 3: EOD bar loading exactly 15 minutes after market close
            # Market closes at 4:00 PM ET → Job 3 runs at 4:15 PM ET (16:15)
            # Runs every weekday (Mon-Fri)
            self.eod_job = self.scheduler.add_job(
                func=self._load_eod_bars,
                trigger=CronTrigger(
                    hour=16,
                    minute=15,
                    day_of_week="mon-fri",
                    timezone='America/New_York'
                ),
                id="eod_bars_job3",
                name="Job 3: EOD Bars (15 min after market close)",
                replace_existing=True,
                max_instances=1,
            )
            
            logger.info("Job 3 scheduled: 16:15 ET (4:15 PM, 15 min after market close) Mon-Fri")

            if settings.FOREX_ENABLED:
                self.forex_job = self.scheduler.add_job(
                    func=self._poll_forex,
                    trigger=CronTrigger(
                        second=self._offset_seconds(settings.FOREX_OFFSET_SECOND),
                        timezone="America/New_York",
                    ),
                    id="forex_poll_job",
                    name="FX: Frankfurter Poll (10s offset)",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )

            if settings.CRYPTO_ENABLED and self.crypto_symbols:
                self.crypto_job = self.scheduler.add_job(
                    func=self._poll_crypto,
                    trigger=CronTrigger(
                        second=self._offset_seconds(settings.CRYPTO_OFFSET_SECOND),
                        timezone="America/New_York",
                    ),
                    id="crypto_poll_job",
                    name="Crypto: Alpaca Poll (10s offset)",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )
            
            self.scheduler.start()
            self.is_running = True
            
            logger.info("Scheduler started successfully with %s jobs", len(self.scheduler.get_jobs()))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}", exc_info=True)
            self.is_running = False
            return False

    def stop(self):
        """Stop the scheduler."""
        try:
            if self.scheduler and self.scheduler.running:
                logger.info("Stopping market data polling scheduler")
                self.scheduler.shutdown(wait=True)
                self.is_running = False
                logger.info("Scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")

    @staticmethod
    def _offset_seconds(offset: int) -> str:
        """Build a wall-clock-aligned ten-second cron field."""
        return ",".join(str((offset + step) % 60) for step in range(0, 60, 10))

    def _poll_market_data_threaded(self):
        """
        Job 1: Poll market data for all validated symbols using threading.
        
        Only runs during market hours (9:30 AM - 4:00 PM ET, Mon-Fri).
        Splits symbols into batches of 100 and uses ThreadPoolExecutor with 5 workers
        for parallel API requests.
        """
        # Check if market is open before executing
        if not is_market_open():
            logger.debug("Market is closed, skipping Job 1 poll")
            return
        
        logger.debug(f"Job 1 triggered: Fetching prices for {len(self.all_symbols)} symbols")
        
        try:
            # Use batch fetching with threading
            result = self.price_service.fetch_and_persist_prices_batch(
                self.all_symbols,
                num_workers=5,
                batch_size=100,
            )
            
            if result["success"]:
                logger.info(
                    f"Job 1 completed successfully: "
                    f"requested={result['total_symbols']}, "
                    f"inserted={result['prices_inserted']}, "
                    f"batches={result['batches_processed']}"
                )
            else:
                logger.warning(
                    f"Job 1 completed with issues: "
                    f"inserted={result['prices_inserted']}, "
                    f"batches_failed={result['batches_failed']}, "
                    f"errors={len(result['errors'])}"
                )
                
        except Exception as e:
            logger.error(f"Job 1 error: {e}", exc_info=True)

    def _load_eod_bars(self):
        """
        Job 3: Load EOD bars for all symbols (runs 15 minutes after market close).
        
        Executes at 4:15 PM ET every weekday (market closes at 4:00 PM ET).
        Fetches the previous day's bar for each symbol and inserts into database.
        """
        logger.info(f"Job 3 triggered: Loading EOD bars for {len(self.eod_symbols)} symbols")
        
        total_success = 0
        total_failed = 0
        errors = []
        
        try:
            for idx, symbol in enumerate(self.eod_symbols, 1):
                try:
                    result = self.bars_service.load_eod_bar(symbol, days_back=1)
                    
                    if result["success"]:
                        total_success += 1
                    else:
                        total_failed += 1
                        if result["errors"]:
                            errors.extend(result["errors"])
                    
                    # Log progress every 50 symbols
                    if idx % 50 == 0:
                        logger.info(
                            f"Job 3 progress: {idx}/{len(self.eod_symbols)} "
                            f"({total_success} success, {total_failed} failed)"
                        )
                        
                except Exception as e:
                    logger.error(f"Job 3 error for {symbol}: {e}")
                    total_failed += 1
                    errors.append(f"{symbol}: {str(e)}")
            
            logger.info(
                f"Job 3 completed: {total_success} successful, {total_failed} failed"
            )
            
            if errors:
                logger.warning(f"Job 3 errors: {errors[:5]}")
                
        except Exception as e:
            logger.error(f"Job 3 fatal error: {e}", exc_info=True)

    def _poll_forex(self):
        """Fetch and persist all directed configured FX rates."""
        try:
            quotes = self.forex_service.get_quotes(settings.forex_currencies_list)
            result = self.price_service.fetch_and_persist_forex_quotes(quotes)
            logger.info(
                "FX poll completed: requested=%s inserted=%s",
                result.get("symbols_requested", 0),
                result.get("prices_inserted", 0),
            )
        except Exception as exc:
            logger.error("FX poll failed: %s", exc, exc_info=True)

    def _poll_crypto(self):
        """Fetch and persist crypto quotes without stock-market gating."""
        try:
            result = self.price_service.fetch_and_persist_crypto_prices(self.crypto_symbols)
            logger.info(
                "Crypto poll completed: requested=%s inserted=%s",
                result.get("symbols_requested", len(self.crypto_symbols)),
                result.get("prices_inserted", 0),
            )
        except Exception as exc:
            logger.error("Crypto poll failed: %s", exc, exc_info=True)

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "is_running": self.is_running,
            "poll_interval_seconds": settings.POLL_INTERVAL_SECONDS,
            "total_symbols": len(self.all_symbols),
            "poll_job": {
                "name": self.poll_job.name if self.poll_job else None,
                "next_run": (
                    self.poll_job.next_run_time.isoformat()
                    if self.poll_job and self.poll_job.next_run_time
                    else None
                ),
            },
            "eod_job": {
                "name": self.eod_job.name if self.eod_job else None,
                "next_run": (
                    self.eod_job.next_run_time.isoformat()
                    if self.eod_job and self.eod_job.next_run_time
                    else None
                ),
            },
            "forex_job": {
                "name": self.forex_job.name if self.forex_job else None,
                "next_run": self.forex_job.next_run_time.isoformat() if self.forex_job and self.forex_job.next_run_time else None,
            },
            "crypto_job": {
                "name": self.crypto_job.name if self.crypto_job else None,
                "next_run": self.crypto_job.next_run_time.isoformat() if self.crypto_job and self.crypto_job.next_run_time else None,
            },
            "job_count": len(self.scheduler.get_jobs()) if self.scheduler else 0,
        }


# Global scheduler instance
_scheduler_manager: Optional[SchedulerManager] = None


def initialize_scheduler(
    price_service: PriceService,
    bars_service: BarsService,
    all_symbols: List[str],
    forex_service: Optional[ForexService] = None,
    crypto_symbols: Optional[List[str]] = None,
    eod_symbols: Optional[List[str]] = None,
) -> SchedulerManager:
    """Initialize and return the global scheduler manager."""
    global _scheduler_manager
    _scheduler_manager = SchedulerManager(
        price_service,
        bars_service,
        all_symbols,
        forex_service,
        crypto_symbols,
        eod_symbols,
    )
    return _scheduler_manager


def get_scheduler() -> Optional[SchedulerManager]:
    """Get the global scheduler manager."""
    return _scheduler_manager
