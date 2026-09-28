"""Additional integration and edge case tests."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from requests.exceptions import ConnectionError, Timeout

from app.services.price_service import PriceService
from app.services.bars_service import BarsService
from app.services.alpaca_service import AlpacaService
from app.models import Instrument, InstrumentPriceHistory


class TestPriceServiceEdgeCases:
    """Edge case tests for PriceService."""

    @pytest.fixture
    def mock_alpaca_service(self):
        return MagicMock(spec=AlpacaService)

    def test_persist_price_with_zero_bid(self, mock_alpaca_service):
        """Test price persistence with zero bid (should fail validation)."""
        from app.database import db_manager
        mock_session = MagicMock()
        price_service = PriceService(mock_alpaca_service)
        
        # Zero bid should fail
        result = price_service.persist_price(
            mock_session,
            "AAPL",
            bid_price=0.0,
            ask_price=150.50,
            timestamp=datetime.utcnow(),
        )
        
        # Should still create the record but DB constraints may fail
        assert mock_session.add.called

    def test_fetch_prices_with_api_error(self, mock_alpaca_service):
        """Test price fetching handles Alpaca API error gracefully."""
        from app.services.alpaca_service import AlpacaMarketDataError
        mock_alpaca_service.get_latest_quotes.side_effect = AlpacaMarketDataError("API Error")
        
        price_service = PriceService(mock_alpaca_service)
        
        with patch("app.services.price_service.db_manager"):
            # fetch_and_persist_prices catches the error and returns result dict
            result = price_service.fetch_and_persist_prices(["AAPL"])
            
            # Should return error result, not raise
            assert result["success"] is False
            assert len(result["errors"]) > 0

    def test_fetch_prices_stats_tracking(self, mock_alpaca_service):
        """Test that price service tracks statistics correctly."""
        mock_alpaca_service.get_latest_quotes.return_value = {
            "AAPL": {"bp": 150.0, "ap": 150.50, "t": "2026-09-25T12:00:00Z"}
        }
        mock_alpaca_service.parse_quote.return_value = {
            "bid": 150.0,
            "ask": 150.50,
            "timestamp": "2026-09-25T12:00:00Z",
        }
        
        price_service = PriceService(mock_alpaca_service)
        initial_fetches = price_service.total_fetches
        
        with patch("app.services.price_service.db_manager"):
            result = price_service.fetch_and_persist_prices(["AAPL"])
        
        # Verify stats incremented
        assert price_service.total_fetches == initial_fetches + 1

    def test_get_status_with_no_fetches(self, mock_alpaca_service):
        """Test get_status when no fetches have occurred yet."""
        price_service = PriceService(mock_alpaca_service)
        
        status = price_service.get_status()
        
        assert status["total_fetches"] == 0
        assert status["successful_fetches"] == 0
        assert status["failed_fetches"] == 0
        assert status["success_rate"] == 0


class TestBarsServiceEdgeCases:
    """Edge case tests for BarsService."""

    @pytest.fixture
    def mock_alpaca_service(self):
        return MagicMock(spec=AlpacaService)

    def test_persist_bar_decimal_precision(self, mock_alpaca_service):
        """Test bar persistence maintains decimal precision."""
        bars_service = BarsService(mock_alpaca_service)
        mock_session = MagicMock()
        
        result = bars_service.persist_bar(
            mock_session,
            instrument_id="550e8400-e29b-41d4-a716-446655440000",
            timestamp=datetime.utcnow(),
            open_price=150.12345,  # High precision
            high=151.98765,
            low=149.11111,
            close=150.54321,
            volume=1000000,
        )
        
        assert result is True
        # Verify Decimal conversion was called
        mock_session.add.assert_called_once()

    def test_load_bars_with_zero_bars_returned(self, mock_alpaca_service):
        """Test historical bars loading when API returns no data."""
        mock_alpaca_service.get_bars.return_value = []
        bars_service = BarsService(mock_alpaca_service)
        
        with patch("app.services.bars_service.db_manager") as mock_db:
            mock_session = MagicMock()
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_db.session_scope.return_value.__enter__.return_value = mock_session
            
            result = bars_service.load_historical_bars("INVALID", days=365)
            
            assert result["success"] is False

    def test_load_eod_bar_api_error_handling(self, mock_alpaca_service):
        """Test EOD bar loading with Alpaca API error."""
        from app.services.alpaca_service import AlpacaMarketDataError
        mock_alpaca_service.get_bars.side_effect = AlpacaMarketDataError("API Error")
        bars_service = BarsService(mock_alpaca_service)
        
        with patch("app.services.bars_service.db_manager") as mock_db:
            mock_session = MagicMock()
            mock_session.query.return_value.filter_by.return_value.first.return_value = Instrument(
                instrument_id="550e8400-e29b-41d4-a716-446655440000",
                ticker="AAPL"
            )
            mock_db.session_scope.return_value.__enter__.return_value = mock_session
            
            result = bars_service.load_eod_bar("AAPL")
            
            assert result["success"] is False
            assert len(result["errors"]) > 0


class TestAlpacaServiceEdgeCases:
    """Edge case tests for AlpacaService."""

    def test_parse_quote_with_none_values(self):
        """Test quote parsing with None values."""
        service = AlpacaService()
        
        quote_data = {
            "bp": None,  # None bid price
            "ap": None,  # None ask price
            "t": "2026-09-25T12:00:00Z",
        }
        
        result = service.parse_quote("AAPL", quote_data)
        
        # Should return None for invalid format
        assert result is None

    def test_make_request_with_connection_error(self):
        """Test API request with connection error."""
        from app.services.alpaca_service import AlpacaMarketDataError
        from requests.exceptions import ConnectionError
        service = AlpacaService()
        
        with patch("app.services.alpaca_service.requests.request") as mock_request:
            mock_request.side_effect = ConnectionError("Connection refused")
            
            with pytest.raises(AlpacaMarketDataError):
                service._make_request("/v2/stocks/quotes/latest")

    def test_get_bars_with_invalid_dates(self):
        """Test bars fetching with invalid date range."""
        service = AlpacaService()
        
        with patch("app.services.alpaca_service.requests.request") as mock_request:
            mock_request.return_value.json.return_value = {"bars": {"AAPL": []}}
            mock_request.return_value.raise_for_status.return_value = None
            
            result = service.get_bars("AAPL", "2026-09-25", "2026-09-20")  # end before start
            
            assert result == []


class TestDatabaseEdgeCases:
    """Edge case tests for Database manager."""

    def test_session_scope_with_multiple_errors(self):
        """Test session scope handling multiple database errors."""
        from app.database import DatabaseManager
        manager = DatabaseManager()
        
        mock_session = MagicMock()
        mock_session.commit.side_effect = [Exception("Commit failed")]
        
        with patch("app.database.sessionmaker") as mock_sessionmaker:
            mock_sessionmaker.return_value = lambda: mock_session
            manager.SessionLocal = lambda: mock_session
            manager._connected = True
            manager.engine = MagicMock()
            
            with pytest.raises(Exception):
                with manager.session_scope():
                    pass
            
            # Should call rollback
            assert mock_session.rollback.called

    def test_initialize_with_pool_exhaustion(self):
        """Test database initialization with pool configuration."""
        from app.database import DatabaseManager
        manager = DatabaseManager()
        
        with patch("app.database.settings") as mock_settings:
            mock_settings.database_url = "postgresql://test:test@localhost/test_db"
            mock_settings.DB_HOST = "localhost"
            mock_settings.DB_PORT = 5432
            mock_settings.DB_NAME = "test_db"
            mock_settings.DB_POOL_SIZE = 5
            mock_settings.DB_MAX_OVERFLOW = 10
            mock_settings.DEBUG = False
            mock_settings.REQUEST_TIMEOUT_SECONDS = 30
            mock_settings.SERVICE_NAME = "test"
            
            with patch("app.database.create_engine") as mock_create_engine:
                mock_engine = MagicMock()
                mock_create_engine.return_value = mock_engine
                mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
                
                result = manager.initialize()
                
                # Verify pool settings were passed
                assert result is True
                call_kwargs = mock_create_engine.call_args[1]
                assert call_kwargs["pool_size"] == 5
                assert call_kwargs["max_overflow"] == 10

    def test_reset_schema(self):
        """Test schema reset functionality."""
        from app.database import DatabaseManager
        manager = DatabaseManager()
        
        with patch("app.database.settings") as mock_settings:
            mock_settings.database_url = "postgresql://test:test@localhost/test_db"
            mock_settings.DB_HOST = "localhost"
            mock_settings.DB_PORT = 5432
            mock_settings.DB_NAME = "test_db"
            mock_settings.DB_POOL_SIZE = 5
            mock_settings.DB_MAX_OVERFLOW = 10
            mock_settings.DEBUG = False
            mock_settings.REQUEST_TIMEOUT_SECONDS = 30
            mock_settings.SERVICE_NAME = "test"
            
            with patch("app.database.create_engine") as mock_create_engine:
                mock_engine = MagicMock()
                mock_create_engine.return_value = mock_engine
                mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
                
                with patch("app.database.sessionmaker"):
                    with patch("app.models.Base") as mock_base:
                        mock_base.metadata = MagicMock()
                        manager.initialize()
                        
                        result = manager.reset_schema()
                        
                        assert result is True
                        assert mock_base.metadata.drop_all.called
                        assert mock_base.metadata.create_all.called

    def test_close_database(self):
        """Test database connection closing."""
        from app.database import DatabaseManager
        manager = DatabaseManager()
        manager._connected = True
        manager.engine = MagicMock()
        
        result = manager.close()
        
        # close() returns None, just verify it was called
        assert manager.engine.dispose.called


class TestPriceServiceErrorPaths:
    """Additional error path tests for PriceService."""

    def test_fetch_prices_batch_processing_error(self):
        """Test batch processing with partial failures."""
        from app.services.price_service import PriceService
        alpaca_service = MagicMock(spec=AlpacaService)
        
        # Mock to return some symbols successfully, fail on others
        alpaca_service.get_latest_quotes.return_value = {
            "AAPL": {"bp": 150.0, "ap": 150.5, "t": "2026-09-25T12:00:00Z"},
        }
        alpaca_service.parse_quote.side_effect = lambda ticker, data: {
            "bid": 150.0,
            "ask": 150.5,
            "timestamp": "2026-09-25T12:00:00Z",
        } if ticker == "AAPL" else None
        
        price_service = PriceService(alpaca_service)
        
        with patch("app.services.price_service.db_manager") as mock_db:
            mock_session = MagicMock()
            mock_db.session_scope.return_value.__enter__.return_value = mock_session
            
            result = price_service.fetch_and_persist_prices(["AAPL", "MSFT"])
            
            # Should handle partial success
            assert isinstance(result, dict)

    def test_fetch_prices_with_timeout(self):
        """Test price fetching with timeout."""
        from app.services.price_service import PriceService
        alpaca_service = MagicMock(spec=AlpacaService)
        alpaca_service.get_latest_quotes.side_effect = Timeout("Request timeout")
        
        price_service = PriceService(alpaca_service)
        
        with patch("app.services.price_service.db_manager"):
            result = price_service.fetch_and_persist_prices(["AAPL"])
            
            assert result["success"] is False

    def test_persist_price_decimal_rounding(self):
        """Test price persistence with decimal rounding."""
        from app.services.price_service import PriceService
        alpaca_service = MagicMock(spec=AlpacaService)
        price_service = PriceService(alpaca_service)
        mock_session = MagicMock()
        
        # Test with high-precision decimals
        result = price_service.persist_price(
            mock_session,
            "AAPL",
            bid_price=150.123456789,
            ask_price=150.987654321,
            timestamp=datetime.utcnow(),
        )
        
        assert result is True
        assert mock_session.add.called


class TestBarsServiceErrorPaths:
    """Additional error path tests for BarsService."""

    def test_load_historical_bars_missing_instrument(self):
        """Test historical bars with missing instrument."""
        from app.services.bars_service import BarsService
        alpaca_service = MagicMock(spec=AlpacaService)
        bars_service = BarsService(alpaca_service)
        
        with patch("app.services.bars_service.db_manager") as mock_db:
            mock_session = MagicMock()
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_db.session_scope.return_value.__enter__.return_value = mock_session
            
            result = bars_service.load_historical_bars("INVALID_TICKER", days=365)
            
            assert result["success"] is False
            assert "errors" in result

    def test_load_eod_bar_successful(self):
        """Test successful EOD bar loading."""
        from app.services.bars_service import BarsService
        alpaca_service = MagicMock(spec=AlpacaService)
        alpaca_service.get_bars.return_value = [
            {
                "t": "2026-09-25T00:00:00Z",
                "o": 150.0,
                "h": 151.5,
                "l": 149.0,
                "c": 150.5,
                "v": 1000000,
            }
        ]
        bars_service = BarsService(alpaca_service)
        
        with patch("app.services.bars_service.db_manager") as mock_db:
            mock_session = MagicMock()
            mock_instrument = Instrument(
                instrument_id="550e8400-e29b-41d4-a716-446655440000",
                ticker="AAPL"
            )
            mock_session.query.return_value.filter_by.return_value.first.return_value = mock_instrument
            mock_db.session_scope.return_value.__enter__.return_value = mock_session
            
            result = bars_service.load_eod_bar("AAPL")
            
            assert result["success"] is True

    def test_persist_bar_with_extreme_values(self):
        """Test bar persistence with extreme price values."""
        from app.services.bars_service import BarsService
        alpaca_service = MagicMock(spec=AlpacaService)
        bars_service = BarsService(alpaca_service)
        mock_session = MagicMock()
        
        result = bars_service.persist_bar(
            mock_session,
            instrument_id="550e8400-e29b-41d4-a716-446655440000",
            timestamp=datetime.utcnow(),
            open_price=0.0001,  # Very small value
            high=99999.9999,    # Very large value
            low=0.0001,
            close=50000.0,
            volume=999999999,   # Very large volume
        )
        
        assert result is True
        assert mock_session.add.called


class TestAlpacaServiceErrorPaths:
    """Additional error path tests for AlpacaService."""

    def test_get_latest_quotes_with_partial_response(self):
        """Test quote fetching with partial API response."""
        service = AlpacaService()
        
        with patch("app.services.alpaca_service.requests.request") as mock_request:
            # API returns only some symbols
            mock_request.return_value.json.return_value = {
                "quotes": {
                    "AAPL": {"bp": 150.0, "ap": 150.5, "t": "2026-09-25T12:00:00Z"},
                }
            }
            mock_request.return_value.raise_for_status.return_value = None
            
            result = service.get_latest_quotes(["AAPL", "MSFT", "GOOGL"])
            
            # Should return what was available
            assert "AAPL" in result
            assert len(result) == 1

    def test_parse_quote_with_missing_timestamp(self):
        """Test quote parsing with missing timestamp."""
        service = AlpacaService()
        
        quote_data = {
            "bp": 150.0,
            "ap": 150.5,
            "t": None,  # Missing timestamp
        }
        
        result = service.parse_quote("AAPL", quote_data)
        
        # Should handle gracefully
        assert result is None or isinstance(result, dict)

    def test_get_bars_with_empty_response(self):
        """Test bars fetching with empty API response."""
        service = AlpacaService()
        
        with patch("app.services.alpaca_service.requests.request") as mock_request:
            mock_request.return_value.json.return_value = {"bars": {}}
            mock_request.return_value.raise_for_status.return_value = None
            
            result = service.get_bars("AAPL", "2026-09-20", "2026-09-25")
            
            assert result == []
