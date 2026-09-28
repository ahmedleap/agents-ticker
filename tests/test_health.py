"""Tests for Health checker service."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from decimal import Decimal

from app.health import HealthChecker
from app.models import Instrument


class TestHealthChecker:
    """Tests for HealthChecker service."""

    @pytest.fixture
    def mock_alpaca_service(self):
        """Create mock Alpaca service."""
        return MagicMock()

    @pytest.fixture
    def mock_price_service(self):
        """Create mock price service."""
        return MagicMock()

    @pytest.fixture
    def health_checker(self, mock_alpaca_service, mock_price_service):
        """Create health checker instance."""
        return HealthChecker(mock_alpaca_service, mock_price_service)

    def test_health_checker_initialization(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test health checker initializes with services."""
        assert health_checker.alpaca == mock_alpaca_service
        assert health_checker.price_service == mock_price_service

    def test_get_health_all_up(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test health check when all components are up."""
        mock_alpaca_service.health_check.return_value = True
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = True
            
            result = health_checker.get_health()
            
            assert result["status"] == "up"
            assert result["database"] == "up"
            assert result["alpaca"] == "up"
            assert "timestamp" in result

    def test_get_health_database_down(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test health check when database is down."""
        mock_alpaca_service.health_check.return_value = True
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = False
            
            result = health_checker.get_health()
            
            assert result["status"] == "degraded"
            assert result["database"] == "down"
            assert result["alpaca"] == "up"

    def test_get_health_alpaca_down(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test health check when Alpaca API is down."""
        mock_alpaca_service.health_check.return_value = False
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = True
            
            result = health_checker.get_health()
            
            assert result["status"] == "degraded"
            assert result["database"] == "up"
            assert result["alpaca"] == "down"

    def test_get_health_both_down(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test health check when both database and Alpaca are down."""
        mock_alpaca_service.health_check.return_value = False
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = False
            
            result = health_checker.get_health()
            
            assert result["status"] == "degraded"
            assert result["database"] == "down"
            assert result["alpaca"] == "down"

    def test_get_health_includes_service_name(self, health_checker, mock_alpaca_service):
        """Test health includes service name."""
        mock_alpaca_service.health_check.return_value = True
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = True
            
            with patch("app.health.settings") as mock_settings:
                mock_settings.SERVICE_NAME = "test-service"
                
                result = health_checker.get_health()
                assert result["service_name"] == "test-service"

    def test_get_market_data_status_success(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test market data status returns stats."""
        mock_price_service.get_status.return_value = {
            "last_successful_fetch": "2026-09-25T12:00:00",
            "last_error": None,
            "total_fetches": 100,
            "successful_fetches": 95,
            "failed_fetches": 5,
            "total_prices_inserted": 50000,
            "success_rate": 95.0,
        }
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = True
            
            with patch("app.health.settings") as mock_settings:
                mock_settings.SERVICE_NAME = "ticker-service"
                mock_settings.symbols_list = ["AAPL", "MSFT"]
                mock_settings.POLL_INTERVAL_SECONDS = 10
                
                result = health_checker.get_market_data_status()
                
                assert result["status"] == "operational"
                assert result["statistics"]["total_fetches"] == 100
                assert result["statistics"]["successful_fetches"] == 95
                assert result["statistics"]["success_rate_percent"] == 95.0

    def test_get_market_data_status_unavailable(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test market data status when database is unavailable."""
        mock_price_service.get_status.return_value = {
            "last_successful_fetch": None,
            "last_error": "Connection refused",
            "total_fetches": 0,
            "successful_fetches": 0,
            "failed_fetches": 0,
            "total_prices_inserted": 0,
            "success_rate": 0,
        }
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = False
            
            with patch("app.health.settings") as mock_settings:
                mock_settings.SERVICE_NAME = "ticker-service"
                mock_settings.symbols_list = []
                mock_settings.POLL_INTERVAL_SECONDS = 10
                
                result = health_checker.get_market_data_status()
                
                assert result["status"] == "unavailable"

    def test_get_readiness_ready(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test readiness probe when service is ready."""
        mock_alpaca_service.health_check.return_value = True
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = True
            
            result = health_checker.get_readiness()
            
            assert result["ready"] is True

    def test_get_readiness_not_ready_database_down(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test readiness probe when database is down."""
        mock_alpaca_service.health_check.return_value = True
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = False
            
            result = health_checker.get_readiness()
            
            assert result["ready"] is False

    def test_get_readiness_not_ready_alpaca_down(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test readiness probe when Alpaca is down."""
        mock_alpaca_service.health_check.return_value = False
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = True
            
            result = health_checker.get_readiness()
            
            assert result["ready"] is False

    def test_get_readiness_includes_database_status(self, health_checker, mock_alpaca_service, mock_price_service):
        """Test readiness includes database and alpaca status."""
        mock_alpaca_service.health_check.return_value = True
        
        with patch("app.health.db_manager") as mock_db:
            mock_db.is_connected = True
            
            result = health_checker.get_readiness()
            
            assert "database_connected" in result
            assert "alpaca_accessible" in result
            assert result["database_connected"] is True
            assert result["alpaca_accessible"] is True
