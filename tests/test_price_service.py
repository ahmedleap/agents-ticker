"""Tests for PriceService."""
import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from app.services.price_service import PriceService
from app.models import Instrument


class TestPriceService:
    """Tests for PriceService."""

    def test_service_initialization(self, mock_alpaca_service):
        """Test service initializes correctly."""
        service = PriceService(mock_alpaca_service)
        assert service.alpaca == mock_alpaca_service
        assert service.total_fetches == 0
        assert service.successful_fetches == 0
        assert service.failed_fetches == 0

    def test_persist_price_with_new_instrument(self, price_service, mock_session):
        """Test persisting price creates new instrument if needed."""
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        
        result = price_service.persist_price(
            mock_session,
            "AAPL",
            bid_price=150.00,
            ask_price=150.50,
            timestamp=datetime.utcnow(),
        )
        
        assert result is True
        mock_session.add.assert_called()

    def test_persist_price_with_existing_instrument(self, price_service, mock_session):
        """Test persisting price updates existing instrument."""
        existing_instrument = Instrument(ticker="AAPL", bid=Decimal("145.00"))
        mock_session.query.return_value.filter_by.return_value.first.return_value = existing_instrument
        
        result = price_service.persist_price(
            mock_session,
            "AAPL",
            bid_price=150.00,
            ask_price=150.50,
            timestamp=datetime.utcnow(),
        )
        
        assert result is True
        assert existing_instrument.bid == Decimal("150.00")
        assert existing_instrument.ask == Decimal("150.50")

    def test_persist_price_handles_exception(self, price_service, mock_session):
        """Test error handling in persist_price."""
        mock_session.query.side_effect = Exception("DB Error")
        
        result = price_service.persist_price(
            mock_session,
            "AAPL",
            150.00,
            150.50,
            datetime.utcnow(),
        )
        
        assert result is False

    @patch("app.services.price_service.db_manager")
    def test_fetch_and_persist_prices_success(self, mock_db, price_service, mock_alpaca_service):
        """Test successful price fetch and persistence."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_latest_quotes.return_value = {
            "AAPL": {"bid": 150.0, "ask": 150.50, "timestamp": "2024-01-15T14:30:00Z"},
        }
        mock_alpaca_service.parse_quote.return_value = {
            "bid": 150.0,
            "ask": 150.50,
            "timestamp": "2024-01-15T14:30:00Z",
        }
        
        result = price_service.fetch_and_persist_prices(["AAPL"])
        
        assert result["success"] is True
        assert result["prices_inserted"] > 0

    @patch("app.services.price_service.db_manager")
    def test_fetch_and_persist_prices_empty_quotes(self, mock_db, price_service, mock_alpaca_service):
        """Test handling of empty quotes response."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_latest_quotes.return_value = {}
        
        result = price_service.fetch_and_persist_prices(["INVALID"])
        
        assert result["success"] is False
        assert len(result["errors"]) > 0

    @patch("app.services.price_service.db_manager")
    def test_fetch_and_persist_prices_invalid_bid_ask(self, mock_db, price_service, mock_alpaca_service):
        """Test validation of bid/ask prices."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_latest_quotes.return_value = {
            "AAPL": {"bid": -150.0, "ask": 150.50, "timestamp": "2024-01-15T14:30:00Z"},  # Invalid negative bid
        }
        mock_alpaca_service.parse_quote.return_value = {
            "bid": -150.0,
            "ask": 150.50,
            "timestamp": "2024-01-15T14:30:00Z",
        }
        
        result = price_service.fetch_and_persist_prices(["AAPL"])
        
        assert result["success"] is False

    @patch("app.services.price_service.db_manager")
    def test_fetch_and_persist_prices_ask_less_than_bid(self, mock_db, price_service, mock_alpaca_service):
        """Test validation of ask >= bid."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_latest_quotes.return_value = {
            "AAPL": {"bid": 150.50, "ask": 150.00, "timestamp": "2024-01-15T14:30:00Z"},  # ask < bid
        }
        mock_alpaca_service.parse_quote.return_value = {
            "bid": 150.50,
            "ask": 150.00,
            "timestamp": "2024-01-15T14:30:00Z",
        }
        
        result = price_service.fetch_and_persist_prices(["AAPL"])
        
        assert result["success"] is False

    @patch("app.services.price_service.db_manager")
    def test_fetch_and_persist_prices_batch(self, mock_db, price_service, mock_alpaca_service):
        """Test batch processing with ThreadPoolExecutor."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_db.session_scope.return_value = mock_session
        
        # Mock Alpaca to return quotes for each symbol
        def get_quotes_side_effect(symbols):
            return {sym: {"bp": 150.0, "ap": 150.50, "t": "2024-01-15T14:30:00Z"} for sym in symbols}
        
        mock_alpaca_service.get_latest_quotes.side_effect = get_quotes_side_effect
        mock_alpaca_service.parse_quote.return_value = {
            "bid": 150.0,
            "ask": 150.50,
            "timestamp": "2024-01-15T14:30:00Z",
        }
        
        symbols = [f"SYM{i}" for i in range(250)]
        result = price_service.fetch_and_persist_prices_batch(symbols, num_workers=5, batch_size=100)
        
        assert result["total_symbols"] == 250
        # Should have 3 batches (100 + 100 + 50)
        assert result["batches_processed"] == 3

    def test_get_latest_price_not_found(self, price_service, mock_alpaca_service):
        """Test getting price for non-existent symbol."""
        with patch("app.services.price_service.db_manager") as mock_db:
            mock_session = MagicMock()
            mock_session.__enter__ = Mock(return_value=mock_session)
            mock_session.__exit__ = Mock(return_value=False)
            mock_session.query.return_value.filter.return_value.first.return_value = None
            mock_db.session_scope.return_value = mock_session
            
            result = price_service.get_latest_price("INVALID")
            assert result is None
