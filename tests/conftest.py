"""Pytest configuration and fixtures."""
import os
import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from app.models import Instrument, InstrumentPriceHistory, Base
from app.database import db_manager
from app.services.alpaca_service import AlpacaService
from app.services.price_service import PriceService
from app.services.bars_service import BarsService


@pytest.fixture
def mock_engine():
    """Mock database engine."""
    return Mock()


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.add = Mock()
    session.commit = Mock()
    session.flush = Mock()
    return session


@pytest.fixture
def mock_alpaca_service():
    """Mock Alpaca service."""
    service = Mock(spec=AlpacaService)
    service.get_latest_quotes.return_value = {
        "AAPL": {"bid": 150.0, "ask": 150.50, "timestamp": "2024-01-15T14:30:00Z"},
        "MSFT": {"bid": 300.0, "ask": 300.50, "timestamp": "2024-01-15T14:30:00Z"},
    }
    service.parse_quote.return_value = {"bid": 150.0, "ask": 150.50, "timestamp": "2024-01-15T14:30:00Z"}
    service.get_bars.return_value = [
        {"open": 150.0, "high": 151.0, "low": 149.0, "close": 150.50, "volume": 1000000}
    ]
    return service


@pytest.fixture
def price_service(mock_alpaca_service):
    """Price service with mocked Alpaca."""
    return PriceService(mock_alpaca_service)


@pytest.fixture
def bars_service(mock_alpaca_service):
    """Bars service with mocked Alpaca."""
    return BarsService(mock_alpaca_service)


@pytest.fixture
def sample_instrument():
    """Sample instrument for testing."""
    return Instrument(
        ticker="AAPL",
        name="Apple Inc.",
        asset_class="STOCK",
        bid=Decimal("150.00"),
        ask=Decimal("150.50"),
        price_updated_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_price_history():
    """Sample price history record."""
    instrument = Instrument(ticker="AAPL", name="Apple", asset_class="STOCK")
    return InstrumentPriceHistory(
        instrument=instrument,
        timestamp=datetime.utcnow(),
        open=Decimal("150.00"),
        high=Decimal("151.00"),
        low=Decimal("149.00"),
        close=Decimal("150.50"),
        volume=1000000,
    )


@pytest.fixture
def db_session_mock():
    """Mock database session with context manager support."""
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    return session
