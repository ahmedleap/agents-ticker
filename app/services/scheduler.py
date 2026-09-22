"""Scheduled tasks for market data polling."""
import logging
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.job import Job

from app.config import settings
from app.services.alpaca_service import AlpacaService
from app.services.price_service import PriceService

logger = logging.getLogger(__name__)


class SchedulerManager:
    """Manages scheduled polling of market data."""

    def __init__(self, price_service: PriceService):
        self.price_service = price_service
        self.scheduler: Optional[BackgroundScheduler] = None
        self.poll_job: Optional[Job] = None
        self.is_running = False

    def start(self) -> bool:
        """
        Start the scheduler and polling job.
        
        Returns:
            True if scheduler started successfully, False otherwise
        """
        try:
            logger.info("Starting market data polling scheduler")
            
            self.scheduler = BackgroundScheduler()
            
            # Schedule the polling job
            self.poll_job = self.scheduler.add_job(
                func=self._poll_market_data,
                trigger=IntervalTrigger(seconds=settings.POLL_INTERVAL_SECONDS),
                id="market_data_poll",
                name="Market Data Poll",
                replace_existing=True,
                max_instances=1,  # Prevent overlapping executions
            )
            
            self.scheduler.start()
            self.is_running = True
            
            logger.info(
                f"Scheduler started successfully. "
                f"Polling interval: {settings.POLL_INTERVAL_SECONDS}s"
            )
            
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

    def _poll_market_data(self):
        """
        Poll market data for configured symbols.
        Called periodically by the scheduler.
        """
        symbols = settings.symbols_list
        
        logger.debug(f"Market data poll triggered for {len(symbols)} symbols")
        
        try:
            result = self.price_service.fetch_and_persist_prices(symbols)
            
            if result["success"]:
                logger.info(
                    f"Fetch completed successfully: "
                    f"requested={result['symbols_requested']}, "
                    f"inserted={result['prices_inserted']}"
                )
            else:
                logger.warning(
                    f"Fetch completed with issues: "
                    f"errors={result['errors']}"
                )
                
        except Exception as e:
            logger.error(f"Unexpected error in poll cycle: {e}", exc_info=True)

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "is_running": self.is_running,
            "poll_interval_seconds": settings.POLL_INTERVAL_SECONDS,
            "next_run": (
                self.poll_job.next_run_time.isoformat()
                if self.poll_job and self.poll_job.next_run_time
                else None
            ),
            "job_count": len(self.scheduler.get_jobs()) if self.scheduler else 0,
        }


# Global scheduler instance (will be initialized in FastAPI app startup)
_scheduler_manager: Optional[SchedulerManager] = None


def initialize_scheduler(price_service: PriceService) -> SchedulerManager:
    """Initialize and return the global scheduler manager."""
    global _scheduler_manager
    _scheduler_manager = SchedulerManager(price_service)
    return _scheduler_manager


def get_scheduler() -> Optional[SchedulerManager]:
    """Get the global scheduler manager."""
    return _scheduler_manager
