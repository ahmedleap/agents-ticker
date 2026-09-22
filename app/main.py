"""FastAPI application for Market Data Service."""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import db_manager
from app.models import Base
from app.services.alpaca_service import AlpacaService
from app.services.price_service import PriceService
from app.services.scheduler import initialize_scheduler, get_scheduler
from app.health import HealthChecker

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)

# Global service instances
alpaca_service: AlpacaService = None
price_service: PriceService = None
health_checker: HealthChecker = None
scheduler_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown.
    """
    global alpaca_service, price_service, health_checker, scheduler_manager
    
    logger.info("Starting Market Data Service...")
    
    # Initialize database
    logger.info("Initializing database connection")
    if not db_manager.initialize():
        logger.error("Failed to initialize database - service will not operate normally")
        sys.exit(1)
    
    # Initialize services
    logger.info("Initializing Alpaca service")
    alpaca_service = AlpacaService()
    
    logger.info("Initializing price service")
    price_service = PriceService(alpaca_service)
    
    logger.info("Initializing health checker")
    health_checker = HealthChecker(alpaca_service, price_service)
    
    # Initialize and start scheduler
    logger.info("Initializing scheduler")
    scheduler_manager = initialize_scheduler(price_service)
    
    if not scheduler_manager.start():
        logger.error("Failed to start scheduler - market data polling will not occur")
    
    logger.info("Market Data Service startup complete")
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down Market Data Service...")
    if scheduler_manager:
        scheduler_manager.stop()
    
    db_manager.close()
    logger.info("Market Data Service shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.SERVICE_NAME,
    description="Market Data Service - Fetches market data from Alpaca and persists to PostgreSQL",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HEALTH & STATUS ENDPOINTS
# ============================================================

@app.get("/health", tags=["Health"])
async def health() -> dict:
    """
    Health check endpoint.
    
    Returns:
        {
            "status": "up|degraded|down",
            "timestamp": "2024-01-15T14:30:00",
            "database": "up|down",
            "alpaca": "up|down",
            "service_name": "market-data-service",
            "uptime_info": "service started"
        }
    """
    if not health_checker:
        raise HTTPException(status_code=503, detail="Service not fully initialized")
    
    return health_checker.get_health()


@app.get("/health/ready", tags=["Health"])
async def readiness() -> dict:
    """
    Kubernetes readiness probe endpoint.
    
    Returns:
        {"ready": true|false, "database_connected": bool, "alpaca_accessible": bool}
    """
    if not health_checker:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "database_connected": False, "alpaca_accessible": False}
        )
    
    status = health_checker.get_readiness()
    status_code = 200 if status["ready"] else 503
    
    return JSONResponse(status_code=status_code, content=status)


@app.get("/market-data/status", tags=["Status"])
async def market_data_status() -> dict:
    """
    Market data service status endpoint.
    
    Returns:
        {
            "service": "market-data-service",
            "status": "operational|unavailable",
            "last_successful_fetch": "2024-01-15T14:30:00",
            "last_error": "error message or null",
            "symbols_tracked": ["AAPL", "MSFT", ...],
            "symbols_count": 7,
            "provider": "alpaca",
            "poll_interval_seconds": 10,
            "statistics": {
                "total_fetches": 42,
                "successful_fetches": 40,
                "failed_fetches": 2,
                "total_prices_inserted": 280,
                "success_rate_percent": 95.24
            }
        }
    """
    if not health_checker:
        raise HTTPException(status_code=503, detail="Service not fully initialized")
    
    return health_checker.get_market_data_status()


# ============================================================
# SCHEDULER CONTROL ENDPOINTS
# ============================================================

@app.get("/scheduler/status", tags=["Scheduler"])
async def scheduler_status() -> dict:
    """
    Get scheduler status.
    
    Returns:
        {
            "is_running": true,
            "poll_interval_seconds": 10,
            "next_run": "2024-01-15T14:30:10",
            "job_count": 1
        }
    """
    scheduler = get_scheduler()
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")
    
    return scheduler.get_status()


# ============================================================
# MARKET DATA QUERY ENDPOINTS
# ============================================================

@app.get("/market-data/latest/{symbol}", tags=["Market Data"])
async def get_latest_price(symbol: str) -> dict:
    """
    Get the latest price for a symbol.
    
    Args:
        symbol: Ticker symbol (e.g., 'AAPL')
        
    Returns:
        {
            "symbol": "AAPL",
            "bid": 150.25,
            "ask": 150.35,
            "midpoint": 150.30,
            "as_of": "2024-01-15T14:30:00"
        }
    """
    if not price_service:
        raise HTTPException(status_code=503, detail="Service not fully initialized")
    
    price_data = price_service.get_latest_price(symbol)
    
    if not price_data:
        raise HTTPException(status_code=404, detail=f"No price data found for {symbol}")
    
    return price_data


# ============================================================
# METADATA ENDPOINTS
# ============================================================

@app.get("/", tags=["Info"])
async def root() -> dict:
    """
    Service information endpoint.
    
    Returns:
        Information about the market data service
    """
    return {
        "service": settings.SERVICE_NAME,
        "version": "1.0.0",
        "status": "operational",
        "documentation": "/docs",
        "endpoints": {
            "health": "GET /health",
            "readiness": "GET /health/ready",
            "market_data_status": "GET /market-data/status",
            "scheduler_status": "GET /scheduler/status",
            "latest_price": "GET /market-data/latest/{symbol}",
        },
    }


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.SERVICE_HOST,
        port=settings.SERVICE_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
