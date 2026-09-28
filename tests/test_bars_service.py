"""Tests for BarsService."""
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from app.services.bars_service import BarsService
from app.models import Instrument, InstrumentPriceHistory


class TestBarsService:
    """Tests for BarsService."""

    def test_service_initialization(self, mock_alpaca_service):
        """Test service initializes correctly."""
        service = BarsService(mock_alpaca_service)
        assert service.alpaca == mock_alpaca_service

    @patch("app.services.bars_service.db_manager")
    def test_load_historical_bars_success(self, mock_db, bars_service, mock_alpaca_service):
        """Test successful historical bars loading (Job 2)."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_bars.return_value = [
            {
                "t": "2024-01-15",
                "o": 150.00,
                "h": 151.50,
                "l": 149.00,
                "c": 150.50,
                "v": 1000000,
            }
            for _ in range(252)  # ~1 year of trading days
        ]
        
        result = bars_service.load_historical_bars("AAPL", days=365)
        
        assert result["success"] is True
        assert result["bars_inserted"] == 252

    @patch("app.services.bars_service.db_manager")
    def test_load_historical_bars_no_data(self, mock_db, bars_service, mock_alpaca_service):
        """Test handling when no historical bars are returned."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_bars.return_value = []
        
        result = bars_service.load_historical_bars("INVALID", days=365)
        
        assert result["success"] is False
        assert result["bars_inserted"] == 0

    @patch("app.services.bars_service.db_manager")
    def test_load_eod_bar_success(self, mock_db, bars_service, mock_alpaca_service):
        """Test successful EOD bar loading (Job 3)."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_bars.return_value = [
            {
                "t": "2024-01-14",
                "o": 150.00,
                "h": 151.50,
                "l": 149.00,
                "c": 150.50,
                "v": 1000000,
            }
        ]
        
        result = bars_service.load_eod_bar("AAPL", days_back=1)
        
        assert result["success"] is True
        assert result["errors"] == []

    @patch("app.services.bars_service.db_manager")
    def test_load_eod_bar_no_data(self, mock_db, bars_service, mock_alpaca_service):
        """Test EOD loading when no bar data available."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_db.session_scope.return_value = mock_session
        
        mock_alpaca_service.get_bars.return_value = []
        
        result = bars_service.load_eod_bar("INVALID")
        
        assert result["success"] is False

    def test_persist_bar_valid_data(self, bars_service):
        """Test persisting a single bar with valid OHLCV data."""
        mock_session = MagicMock()
        
        result = bars_service.persist_bar(
            mock_session,
            instrument_id="550e8400-e29b-41d4-a716-446655440000",
            timestamp=datetime(2024, 1, 15),
            open_price=150.00,
            high=151.50,
            low=149.00,
            close=150.50,
            volume=1000000,
        )
        
        assert result is True
        # Verify session.add was called
        mock_session.add.assert_called_once()

    def test_persist_bar_with_timezone(self, bars_service):
        """Test persisting a bar with timezone-aware timestamp."""
        from datetime import timezone
        mock_session = MagicMock()
        tz_timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        result = bars_service.persist_bar(
            mock_session,
            instrument_id="550e8400-e29b-41d4-a716-446655440000",
            timestamp=tz_timestamp,
            open_price=150.00,
            high=151.50,
            low=149.00,
            close=150.50,
            volume=1000000,
        )
        
        assert result is True

    def test_persist_bar_exception_handling(self, bars_service):
        """Test error handling during persistence."""
        mock_session = MagicMock()
        mock_session.add.side_effect = Exception("DB error")
        
        result = bars_service.persist_bar(
            mock_session,
            instrument_id="550e8400-e29b-41d4-a716-446655440000",
            timestamp=datetime(2024, 1, 15),
            open_price=150.00,
            high=151.50,
            low=149.00,
            close=150.50,
            volume=1000000,
        )
        
        assert result is False
