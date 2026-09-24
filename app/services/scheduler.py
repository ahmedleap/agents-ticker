"""Scheduled tasks for market data polling."""
import logging
from datetime import datetime, time
from typing import Optional, List
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job

from app.config import settings
from app.services.alpaca_service import AlpacaService
from app.services.price_service import PriceService
from app.services.bars_service import BarsService
from app.database import db_manager
from app.models import Instrument

logger = logging.getLogger(__name__)


class SchedulerManager:
    """Manages scheduled polling of market data with threading support."""

    def __init__(self, price_service: PriceService, bars_service: BarsService, all_symbols: List[str]):
        self.price_service = price_service
        self.bars_service = bars_service
        self.all_symbols = all_symbols  # All 469 symbols for Job 1
        self.scheduler: Optional[BackgroundScheduler] = None
        self.poll_job: Optional[Job] = None
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
            
            # Job 1: Real-time quote fetching every 10 seconds
            # Uses threading to batch 469 symbols into 5 requests of ~94 each
            self.poll_job = self.scheduler.add_job(
                func=self._poll_market_data_threaded,
                trigger=IntervalTrigger(seconds=settings.POLL_INTERVAL_SECONDS),
                id="market_data_poll_job1",
                name="Job 1: Real-time Price Poll (Threaded)",
                replace_existing=True,
                max_instances=1,
                coalesce=True,  # Skip missed runs if scheduler is overloaded
            )
            
            logger.info(
                f"Job 1 scheduled: Every {settings.POLL_INTERVAL_SECONDS}s, "
                f"{len(self.all_symbols)} symbols, 5 workers, 100 symbols/batch"
            )
            
            # Job 3: EOD bar loading daily at 4:15 PM ET (16:15)
            # Runs at 16:15 every weekday (Mon-Fri)
            self.eod_job = self.scheduler.add_job(
                func=self._load_eod_bars,
                trigger=CronTrigger(hour=16, minute=15, day_of_week="mon-fri"),
                id="eod_bars_job3",
                name="Job 3: EOD Bars (Daily)",
                replace_existing=True,
                max_instances=1,
            )
            
            logger.info("Job 3 scheduled: Daily at 16:15 (4:15 PM ET)")
            
            self.scheduler.start()
            self.is_running = True
            
            logger.info("Scheduler started successfully with 2 jobs")
            
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

    def _poll_market_data_threaded(self):
        """
        Job 1: Poll market data for all 469 symbols using threading.
        
        Splits symbols into batches of 100 and uses ThreadPoolExecutor with 5 workers
        for parallel API requests.
        """
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
        Job 3: Load EOD bars for all symbols (runs daily at market close + 15 min).
        
        Fetches the previous day's bar for each symbol and inserts into database.
        """
        logger.info(f"Job 3 triggered: Loading EOD bars for {len(self.all_symbols)} symbols")
        
        total_success = 0
        total_failed = 0
        errors = []
        
        try:
            for idx, symbol in enumerate(self.all_symbols, 1):
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
                            f"Job 3 progress: {idx}/{len(self.all_symbols)} "
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
            "job_count": len(self.scheduler.get_jobs()) if self.scheduler else 0,
        }


# Global scheduler instance
_scheduler_manager: Optional[SchedulerManager] = None


def initialize_scheduler(
    price_service: PriceService,
    bars_service: BarsService,
    all_symbols: List[str],
) -> SchedulerManager:
    """Initialize and return the global scheduler manager."""
    global _scheduler_manager
    _scheduler_manager = SchedulerManager(price_service, bars_service, all_symbols)
    return _scheduler_manager


def get_scheduler() -> Optional[SchedulerManager]:
    """Get the global scheduler manager."""
    return _scheduler_manager
