"""Health check and status endpoints."""
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from app.config import settings
from app.database import db_manager
from app.services.alpaca_service import AlpacaService
from app.services.price_service import PriceService

logger = logging.getLogger(__name__)


class HealthChecker:
    """Provides health and status information."""

    def __init__(
        self,
        alpaca_service: AlpacaService,
        price_service: PriceService,
    ):
        self.alpaca = alpaca_service
        self.price_service = price_service

    def get_health(self) -> Dict[str, Any]:
        """
        Get overall service health.
        
        Returns:
            Dictionary with health status
        """
        db_status = "up" if db_manager.is_connected else "down"
        alpaca_status = "up" if self.alpaca.health_check() else "down"
        
        overall_status = "up" if (db_status == "up" and alpaca_status == "up") else "degraded"
        
        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "database": db_status,
            "alpaca": alpaca_status,
            "service_name": settings.SERVICE_NAME,
            "uptime_info": "service started",
        }

    def get_market_data_status(self) -> Dict[str, Any]:
        """
        Get market data service status.
        
        Returns:
            Dictionary with market data status
        """
        price_stats = self.price_service.get_status()
        
        return {
            "service": settings.SERVICE_NAME,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "operational" if db_manager.is_connected else "unavailable",
            "last_successful_fetch": price_stats["last_successful_fetch"],
            "last_error": price_stats["last_error"],
            "symbols_tracked": settings.symbols_list,
            "symbols_count": len(settings.symbols_list),
            "provider": "alpaca",
            "poll_interval_seconds": settings.POLL_INTERVAL_SECONDS,
            "statistics": {
                "total_fetches": price_stats["total_fetches"],
                "successful_fetches": price_stats["successful_fetches"],
                "failed_fetches": price_stats["failed_fetches"],
                "total_prices_inserted": price_stats["total_prices_inserted"],
                "success_rate_percent": round(price_stats["success_rate"], 2),
            },
        }

    def get_readiness(self) -> Dict[str, Any]:
        """
        Get readiness status (for k8s probes).
        
        Returns:
            Dictionary with readiness status
        """
        ready = (
            db_manager.is_connected
            and self.alpaca.health_check()
        )
        
        return {
            "ready": ready,
            "database_connected": db_manager.is_connected,
            "alpaca_accessible": self.alpaca.health_check(),
        }
