"""Tests for AlpacaService."""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import responses

from app.services.alpaca_service import AlpacaService, AlpacaMarketDataError, AlpacaTimeoutError


class TestAlpacaService:
    """Tests for Alpaca API service."""

    @pytest.fixture
    def alpaca_service(self):
        """Create Alpaca service instance."""
        return AlpacaService()

    def test_service_initialization(self, alpaca_service):
        """Test service initializes with correct data URL."""
        assert alpaca_service.data_url == "https://data.alpaca.markets"
        assert alpaca_service.headers["APCA-API-KEY-ID"] is not None

    @responses.activate
    def test_get_latest_quotes_success(self, alpaca_service):
        """Test successful quote fetching."""
        responses.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/quotes/latest",
            json={
                "quotes": {
                    "AAPL": {
                        "bid": 150.00,
                        "ask": 150.50,
                        "bids": 1000,
                        "asks": 1000,
                        "last": 150.25,
                        "t": "2024-01-15T14:30:00Z",
                    },
                    "MSFT": {
                        "bid": 300.00,
                        "ask": 300.50,
                        "bids": 1000,
                        "asks": 1000,
                        "last": 300.25,
                        "t": "2024-01-15T14:30:00Z",
                    },
                }
            },
            status=200,
        )
        
        quotes = alpaca_service.get_latest_quotes(["AAPL", "MSFT"])
        
        assert "AAPL" in quotes
        assert "MSFT" in quotes
        assert quotes["AAPL"]["bid"] == 150.00
        assert quotes["AAPL"]["ask"] == 150.50

    @responses.activate
    def test_get_latest_quotes_empty_response(self, alpaca_service):
        """Test handling of empty quote response."""
        responses.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/quotes/latest",
            json={"quotes": {}},
            status=200,
        )
        
        quotes = alpaca_service.get_latest_quotes(["INVALID"])
        assert quotes == {}

    @responses.activate
    def test_get_latest_quotes_api_error(self, alpaca_service):
        """Test API error handling."""
        responses.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/quotes/latest",
            json={"message": "Unauthorized"},
            status=401,
        )
        
        with pytest.raises(AlpacaMarketDataError):
            alpaca_service.get_latest_quotes(["AAPL"])

    def test_parse_quote_success(self, alpaca_service):
        """Test successful quote parsing (Alpaca v2 format)."""
        quote_data = {
            "bp": 150.00,  # bid price
            "ap": 150.50,  # ask price
            "bs": 1000,    # bid size
            "as": 1000,    # ask size
            "t": "2024-01-15T14:30:00Z",
        }
        
        parsed = alpaca_service.parse_quote("AAPL", quote_data)
        
        assert parsed is not None
        assert parsed["bid"] == 150.00
        assert parsed["ask"] == 150.50
        assert parsed["timestamp"] == "2024-01-15T14:30:00Z"

    def test_parse_quote_missing_fields(self, alpaca_service):
        """Test parsing quote with missing Alpaca v2 format returns None."""
        quote_data = {"bid": 150.00}  # Wrong format, not Alpaca v2
        
        parsed = alpaca_service.parse_quote("AAPL", quote_data)
        
        # Should return None for unsupported format
        assert parsed is None

    @responses.activate
    def test_get_bars_success(self, alpaca_service):
        """Test successful bars fetching."""
        responses.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/bars",
            json={
                "bars": {
                    "AAPL": [
                        {
                            "t": "2024-01-15T00:00:00Z",
                            "o": 150.00,
                            "h": 151.50,
                            "l": 149.00,
                            "c": 150.50,
                            "v": 1000000,
                        }
                    ]
                }
            },
            status=200,
        )
        
        bars = alpaca_service.get_bars(
            "AAPL",
            start_date="2024-01-15",
            end_date="2024-01-16"
        )
        
        assert len(bars) > 0
        assert bars[0]["o"] == 150.00
        assert bars[0]["c"] == 150.50

    @responses.activate
    def test_get_bars_empty_response(self, alpaca_service):
        """Test handling of empty bars response."""
        responses.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/bars",
            json={"bars": {"INVALID": []}},
            status=200,
        )
        
        bars = alpaca_service.get_bars("INVALID", "2024-01-15", "2024-01-16")
        assert bars == []

    @responses.activate
    def test_health_check_success(self, alpaca_service):
        """Test health check passes on successful response."""
        responses.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/quotes/latest",
            json={"quotes": {"AAPL": {"bp": 150, "ap": 151}}},
            status=200,
        )
        
        result = alpaca_service.health_check()
        assert result is True

    @responses.activate
    def test_health_check_failure(self, alpaca_service):
        """Test health check fails on API error."""
        responses.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/quotes/latest",
            json={"message": "Unauthorized"},
            status=401,
        )
        
        result = alpaca_service.health_check()
        assert result is False
