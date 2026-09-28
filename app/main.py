"""FastAPI application for Market Data Service."""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import db_manager
from app.models import Base, Instrument
from app.services.alpaca_service import AlpacaService
from app.services.price_service import PriceService
from app.services.bars_service import BarsService
from app.services.scheduler import initialize_scheduler, get_scheduler
from app.health import HealthChecker
from app.bootstrap_instruments import load_symbols_from_file, bootstrap_instruments

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
bars_service: BarsService = None
health_checker: HealthChecker = None
scheduler_manager = None
all_symbols = []  # All valid symbols from instruments table (or overlap.txt fallback)


def load_symbols_from_overlap() -> list:
    """
    Load symbols from database (primary) or overlap.txt (fallback).
    
    Returns symbols that are already bootstrapped in the instruments table.
    Falls back to overlap.txt only if database has no instruments.
    """
    try:
        # Try to load from database first
        with db_manager.session_scope() as session:
            instruments = session.query(Instrument.ticker).all()
            if instruments:
                symbols = sorted([row[0].upper() for row in instruments])
                logger.info(f"Loaded {len(symbols)} symbols from database")
                return symbols
        
        # Fallback: Load from overlap.txt if database is empty
        logger.info("No instruments in database, loading from overlap.txt as fallback")
        symbol_file = Path(__file__).parent.parent / "overlap.txt"
        symbols = []
        
        with open(symbol_file, "r") as f:
            for line in f:
                line = line.strip()
                # Skip header lines and empty lines
                if (
                    line
                    and not line.startswith("OVERLAPPING")
                    and not line.startswith("Generated")
                    and not line.startswith("Total")
                    and not line.startswith("=")
                    and len(line) <= 10
                ):
                    symbols.append(line.upper())
        
        # Remove duplicates and sort
        symbols = sorted(list(set(symbols)))
        logger.info(f"Loaded {len(symbols)} symbols from overlap.txt fallback")
        return symbols
        
    except Exception as e:
        logger.error(f"Failed to load symbols: {e}")
        logger.warning("Service will run with empty symbol list - prices will not be fetched")
        return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown.
    Automatically runs bootstrap if database is empty.
    """
    global alpaca_service, price_service, bars_service, health_checker, scheduler_manager, all_symbols
    
    logger.info("Starting Market Data Service...")
    
    # Initialize database connection only
    logger.info("Initializing database connection")
    if not db_manager.initialize():
        logger.error("Failed to initialize database")
        sys.exit(1)
    
    # Check if instruments table is empty and run bootstrap if needed
    try:
        with db_manager.session_scope() as session:
            instrument_count = session.query(Instrument).count()
            
            if instrument_count == 0:
                logger.warning("Instruments table is empty - running auto-bootstrap")
                
                # Load symbols from overlap.txt
                symbol_file = Path(__file__).parent.parent / "overlap.txt"
                symbols = load_symbols_from_file(str(symbol_file))
                
                if not symbols:
                    logger.error("Failed to load symbols from overlap.txt")
                    sys.exit(1)
                
                logger.info(f"Starting bootstrap for {len(symbols)} symbols...")
                bootstrap_result = bootstrap_instruments(symbols)
                
                logger.info(
                    f"Bootstrap complete: {bootstrap_result['created']} created, "
                    f"{bootstrap_result['already_exist']} already exist, "
                    f"{len(bootstrap_result['invalid'])} invalid"
                )
                
                if bootstrap_result['errors']:
                    logger.warning(f"Bootstrap errors: {bootstrap_result['errors']}")
                
                if bootstrap_result['created'] == 0 and bootstrap_result['already_exist'] == 0:
                    logger.error("No instruments created during bootstrap")
                    sys.exit(1)
            else:
                logger.info(f"Found {instrument_count} existing instruments in database")
    
    except Exception as e:
        logger.error(f"Error during bootstrap check: {e}")
        sys.exit(1)
    
    # Load symbols from database (assume instruments table now has data)
    logger.info("Loading validated symbols from database")
    all_symbols = load_symbols_from_overlap()
    if not all_symbols:
        logger.error("No symbols found in database after bootstrap")
        sys.exit(1)
    
    logger.info(f"Loaded {len(all_symbols)} symbols for Job 1")
    
    # Initialize services
    logger.info("Initializing Alpaca service")
    alpaca_service = AlpacaService()
    
    logger.info("Initializing price service")
    price_service = PriceService(alpaca_service)
    
    logger.info("Initializing bars service")
    bars_service = BarsService(alpaca_service)
    
    logger.info("Initializing health checker")
    health_checker = HealthChecker(alpaca_service, price_service)
    
    # Initialize and start scheduler with all symbols
    logger.info("Initializing scheduler with all jobs")
    scheduler_manager = initialize_scheduler(price_service, bars_service, all_symbols)
    
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
    version="0.3.8",
    lifespan=lifespan,
)

# ============================================================
# HEALTH & STATUS ENDPOINTS (Only)
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
