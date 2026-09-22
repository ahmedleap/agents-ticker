"""Configuration management for Market Data Service."""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Service Configuration
    SERVICE_NAME: str = "market-data-service"
    SERVICE_PORT: int = 8000
    SERVICE_HOST: str = "0.0.0.0"
    DEBUG: bool = False

    # Database Configuration
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", 5432))
    DB_NAME: str = os.getenv("DB_NAME", "agents_of_leap")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Alpaca Configuration
    ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
    ALPACA_DATA_URL: str = "https://data.alpaca.markets"
    # Feed selection - IMPORTANT: Different feeds have different data coverage
    # - iex: Free but limited. Returns ap=0 (no ask price) for many stocks like AMZN, BND
    # - delayed_sip: 15-min delayed but full data coverage. Returns real ask prices.
    # - sip: Real-time all exchanges, requires paid unlimited subscription
    # See: https://docs.alpaca.markets/us/reference/stocklatestquotes-1#query-params-feed
    ALPACA_FEED: str = os.getenv("ALPACA_FEED", "delayed_sip")

    # Polling Configuration
    POLL_INTERVAL_SECONDS: int = 10
    REQUEST_TIMEOUT_SECONDS: int = 30
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_FACTOR: float = 2.0

    # Symbols to track (comma-separated)
    TRACKED_SYMBOLS: str = os.getenv("TRACKED_SYMBOLS", "AAPL,MSFT,GOOGL,AMZN,TSLA,SPY,QQQ")

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json or text

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def database_url(self) -> str:
        """Generate SQLAlchemy database URL."""
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def symbols_list(self) -> list[str]:
        """Parse tracked symbols from configuration."""
        return [s.strip().upper() for s in self.TRACKED_SYMBOLS.split(",") if s.strip()]


# Global settings instance
settings = Settings()
