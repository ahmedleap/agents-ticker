"""Alpaca API integration for market data retrieval."""
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from app.config import settings

logger = logging.getLogger(__name__)


class AlpacaMarketDataError(Exception):
    """Base exception for Alpaca market data errors."""
    pass


class AlpacaTimeoutError(AlpacaMarketDataError):
    """Exception raised when Alpaca API call times out."""
    pass


class AlpacaService:
    """Service for fetching market data from Alpaca."""

    def __init__(self):
        self.api_key = settings.ALPACA_API_KEY
        self.secret_key = settings.ALPACA_SECRET_KEY
        self.data_url = settings.ALPACA_DATA_URL
        self.feed = settings.ALPACA_FEED
        self.timeout = settings.REQUEST_TIMEOUT_SECONDS
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make HTTP request to Alpaca API.
        
        Args:
            endpoint: API endpoint path
            method: HTTP method (GET, POST, etc.)
            params: Query parameters
            
        Returns:
            JSON response from API
            
        Raises:
            AlpacaTimeoutError: If request times out
            AlpacaMarketDataError: For other API errors
        """
        url = f"{self.data_url}{endpoint}"
        
        try:
            logger.debug(f"Making request to Alpaca: {method} {url}")
            
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                timeout=self.timeout,
            )
            
            response.raise_for_status()
            return response.json()
            
        except Timeout as e:
            logger.error(f"Alpaca API timeout: {e}")
            raise AlpacaTimeoutError(f"Request to {endpoint} timed out after {self.timeout}s") from e
            
        except ConnectionError as e:
            logger.error(f"Alpaca connection error: {e}")
            raise AlpacaMarketDataError(f"Failed to connect to Alpaca: {e}") from e
            
        except RequestException as e:
            logger.error(f"Alpaca API request error: {e}")
            raise AlpacaMarketDataError(f"Alpaca API error: {e}") from e

    def get_latest_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch latest quotes for multiple symbols.
        
        Args:
            symbols: List of ticker symbols (e.g., ['AAPL', 'MSFT'])
            
        Returns:
            Dictionary mapping symbols to quote data with bid/ask prices
            
        Example:
            {
                'AAPL': {
                    'bid': 150.25,
                    'ask': 150.35,
                    'timestamp': '2024-01-15T14:30:00Z'
                }
            }
        """
        if not symbols:
            logger.warning("No symbols provided for quote request")
            return {}

        try:
            symbols_str = ",".join(symbols)
            logger.info(f"Fetching quotes for {len(symbols)} symbols: {symbols_str}")
            
            params = {
                "symbols": symbols_str,
                "feed": self.feed,
            }
            
            response = self._make_request("/v2/stocks/quotes/latest", params=params)
            
            quotes = {}
            if "quotes" in response:
                quotes = response["quotes"]
                logger.info(f"Successfully fetched {len(quotes)} quotes from Alpaca")
            else:
                logger.warning(f"No quotes in Alpaca response: {response}")
            
            return quotes
            
        except AlpacaMarketDataError as e:
            logger.error(f"Failed to fetch quotes: {e}")
            raise

    def health_check(self) -> bool:
        """
        Check if Alpaca API is accessible by fetching a quote.
        
        Returns:
            True if API is accessible, False otherwise
        """
        try:
            logger.debug("Checking Alpaca API health")
            # Use the same endpoint as the service (data API, not trading API)
            response = requests.get(
                f"{self.data_url}/v2/stocks/quotes/latest",
                headers=self.headers,
                params={"symbols": "AAPL", "feed": self.feed},
                timeout=5,
            )
            
            if response.status_code == 200:
                logger.debug("Alpaca API health check passed")
                return True
            else:
                logger.warning(f"Alpaca health check returned status {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"Alpaca health check failed: {e}")
            return False

    def parse_quote(self, symbol: str, quote_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse Alpaca quote data and extract bid/ask prices.
        
        Args:
            symbol: Ticker symbol
            quote_data: Raw quote data from Alpaca
            
        Returns:
            Parsed quote with bid, ask, and timestamp or None if parsing fails
        """
        try:
            # Alpaca v2 structure
            if "bp" in quote_data and "ap" in quote_data:
                return {
                    "symbol": symbol,
                    "bid": float(quote_data.get("bp", 0)),
                    "ask": float(quote_data.get("ap", 0)),
                    "bid_size": int(quote_data.get("bs", 0)),
                    "ask_size": int(quote_data.get("as", 0)),
                    "timestamp": quote_data.get("t", datetime.utcnow().isoformat()),
                }
            # Fallback for different API versions
            elif "bidprice" in quote_data and "askprice" in quote_data:
                return {
                    "symbol": symbol,
                    "bid": float(quote_data.get("bidprice", 0)),
                    "ask": float(quote_data.get("askprice", 0)),
                    "timestamp": quote_data.get("timestamp", datetime.utcnow().isoformat()),
                }
            else:
                logger.warning(f"Unknown quote format for {symbol}: {quote_data}")
                return None
                
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"Error parsing quote for {symbol}: {e}")
            return None

    def get_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1Day",
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical OHLC bars for a symbol.
        
        Note: On Basic plan, end_date must be at least 15 minutes in the past
        and feed defaults to 'iex'.
        
        Args:
            symbol: Ticker symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            timeframe: Bar timeframe (1Day, 1Hour, 15Min, etc.)
            
        Returns:
            List of bar data with OHLCV
            
        Example:
            [
                {
                    't': '2026-08-24T00:00:00Z',
                    'o': 311.47,
                    'h': 313.34,
                    'l': 310.05,
                    'c': 310.38,
                    'v': 50000000
                }
            ]
        """
        try:
            logger.debug(f"Fetching bars for {symbol} from {start_date} to {end_date}")
            
            params = {
                "symbols": symbol,
                "start": start_date,
                "end": end_date,
                "timeframe": timeframe,
                "feed": "iex",  # Explicitly use IEX for Basic plan compatibility
                "limit": 10000,
            }
            
            response = self._make_request("/v2/stocks/bars", params=params)
            
            bars = []
            if "bars" in response and symbol in response["bars"]:
                bars = response["bars"][symbol]
                logger.info(f"Successfully fetched {len(bars)} bars for {symbol}")
            else:
                logger.warning(f"No bars found in response for {symbol}")
            
            return bars
            
        except AlpacaMarketDataError as e:
            logger.error(f"Failed to fetch bars for {symbol}: {e}")
            raise
