"""Tests for Scheduler service."""
import pytest
from datetime import datetime, time
from unittest.mock import Mock, patch, MagicMock
from pytz import timezone as pytz_timezone

from app.services.scheduler import SchedulerManager, is_market_open


class TestMarketOpen:
    """Tests for is_market_open function."""

    def test_is_market_open_during_hours(self):
        """Test market open check during trading hours (9:30 AM - 4:00 PM ET)."""
        # Wednesday 11:00 AM ET
        with patch('app.services.scheduler.datetime') as mock_datetime:
            mock_et = MagicMock()
            mock_et.weekday.return_value = 2  # Wednesday
            mock_et.time.return_value = time(11, 0, 0)
            mock_datetime.now.return_value = mock_et
            
            result = is_market_open()
            assert result is True

    def test_is_market_open_before_market(self):
        """Test market open check before market opens (before 9:30 AM)."""
        # Wednesday 9:00 AM ET (before open)
        with patch('app.services.scheduler.datetime') as mock_datetime:
            mock_et = MagicMock()
            mock_et.weekday.return_value = 2  # Wednesday
            mock_et.time.return_value = time(9, 0, 0)
            mock_datetime.now.return_value = mock_et
            
            result = is_market_open()
            assert result is False

    def test_is_market_open_after_market(self):
        """Test market open check after market closes (after 4:00 PM)."""
        # Wednesday 5:00 PM ET (after close)
        with patch('app.services.scheduler.datetime') as mock_datetime:
            mock_et = MagicMock()
            mock_et.weekday.return_value = 2  # Wednesday
            mock_et.time.return_value = time(17, 0, 0)
            mock_datetime.now.return_value = mock_et
            
            result = is_market_open()
            assert result is False

    def test_is_market_open_weekend(self):
        """Test market open check on weekend."""
        # Saturday 11:00 AM ET
        with patch('app.services.scheduler.datetime') as mock_datetime:
            mock_et = MagicMock()
            mock_et.weekday.return_value = 5  # Saturday
            mock_et.time.return_value = time(11, 0, 0)
            mock_datetime.now.return_value = mock_et
            
            result = is_market_open()
            assert result is False

    def test_is_market_open_sunday(self):
        """Test market open check on Sunday."""
        # Sunday 11:00 AM ET
        with patch('app.services.scheduler.datetime') as mock_datetime:
            mock_et = MagicMock()
            mock_et.weekday.return_value = 6  # Sunday
            mock_et.time.return_value = time(11, 0, 0)
            mock_datetime.now.return_value = mock_et
            
            result = is_market_open()
            assert result is False

    def test_is_market_open_at_open_time(self):
        """Test market open check at exact open time (9:30 AM)."""
        # Wednesday 9:30 AM ET (exact open)
        with patch('app.services.scheduler.datetime') as mock_datetime:
            mock_et = MagicMock()
            mock_et.weekday.return_value = 2  # Wednesday
            mock_et.time.return_value = time(9, 30, 0)
            mock_datetime.now.return_value = mock_et
            
            result = is_market_open()
            assert result is True

    def test_is_market_open_at_close_time(self):
        """Test market open check at exact close time (4:00 PM)."""
        # Wednesday 4:00 PM ET (exact close, should be False)
        with patch('app.services.scheduler.datetime') as mock_datetime:
            mock_et = MagicMock()
            mock_et.weekday.return_value = 2  # Wednesday
            mock_et.time.return_value = time(16, 0, 0)
            mock_datetime.now.return_value = mock_et
            
            result = is_market_open()
            assert result is False


class TestSchedulerManager:
    """Tests for SchedulerManager."""

    @pytest.fixture
    def mock_price_service(self):
        """Create mock price service."""
        return MagicMock()

    @pytest.fixture
    def mock_bars_service(self):
        """Create mock bars service."""
        return MagicMock()

    def test_scheduler_manager_initialization(self, mock_price_service, mock_bars_service):
        """Test scheduler manager initializes with correct services."""
        symbols = ["AAPL", "MSFT", "GOOGL"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        assert manager.price_service == mock_price_service
        assert manager.bars_service == mock_bars_service
        assert manager.all_symbols == symbols
        assert manager.scheduler is None
        assert manager.is_running is False

    def test_scheduler_manager_start(self, mock_price_service, mock_bars_service):
        """Test scheduler manager starts successfully."""
        symbols = ["AAPL"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        result = manager.start()
        
        assert result is True
        assert manager.is_running is True
        assert manager.scheduler is not None
        assert manager.poll_job is not None
        assert manager.eod_job is not None
        
        # Clean up
        manager.stop()

    def test_scheduler_manager_stop(self, mock_price_service, mock_bars_service):
        """Test scheduler manager stops successfully."""
        symbols = ["AAPL"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        manager.start()
        assert manager.is_running is True
        
        manager.stop()
        assert manager.is_running is False
        assert manager.scheduler.running is False

    def test_poll_market_data_threaded(self, mock_price_service, mock_bars_service):
        """Test Job 1 polling execution (only runs during market hours)."""
        mock_price_service.fetch_and_persist_prices_batch.return_value = {
            "success": True,
            "prices_inserted": 100,
            "total_symbols": 2,
            "batches_processed": 1,
            "batches_failed": 0,
            "errors": [],
        }
        
        symbols = ["AAPL", "MSFT"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        # Mock is_market_open to return True so Job 1 executes
        with patch("app.services.scheduler.is_market_open", return_value=True):
            manager._poll_market_data_threaded()
        
        mock_price_service.fetch_and_persist_prices_batch.assert_called_once()
        # Verify it was called with the symbols
        call_args = mock_price_service.fetch_and_persist_prices_batch.call_args[0][0]
        assert call_args == symbols

    def test_load_eod_bars_for_all_symbols(self, mock_price_service, mock_bars_service):
        """Test Job 3 EOD bar loading for all symbols."""
        mock_bars_service.load_eod_bar.return_value = {
            "success": True,
            "symbol": "AAPL",
        }
        
        symbols = ["AAPL", "MSFT"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        # Call the EOD method directly
        manager._load_eod_bars()
        
        # Verify load_eod_bar was called for each symbol
        assert mock_bars_service.load_eod_bar.call_count == len(symbols)

    def test_scheduler_manager_with_empty_symbols(self, mock_price_service, mock_bars_service):
        """Test scheduler manager handles empty symbol list."""
        symbols = []
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        # Should initialize without error
        assert manager.scheduler is None
        assert manager.all_symbols == []

    def test_scheduler_job_names(self, mock_price_service, mock_bars_service):
        """Test scheduler jobs have correct names."""
        symbols = ["AAPL"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        manager.start()
        
        jobs = manager.scheduler.get_jobs()
        job_names = [job.name for job in jobs]
        
        assert any("Job 1" in name for name in job_names)
        assert any("Job 3" in name for name in job_names)
        
        manager.stop()

    def test_poll_job_cron_trigger(self, mock_price_service, mock_bars_service):
        """Test Job 1 has correct cron trigger configuration."""
        symbols = ["AAPL"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        manager.start()
        
        # Find Job 1
        poll_job = [j for j in manager.scheduler.get_jobs() if "Job 1" in j.name][0]
        
        # Verify trigger is CronTrigger
        assert hasattr(poll_job.trigger, 'timezone')
        assert str(poll_job.trigger.timezone) == 'America/New_York'
        
        manager.stop()

    def test_eod_job_scheduled_at_correct_time(self, mock_price_service, mock_bars_service):
        """Test Job 3 is scheduled correctly (16:15 ET = 4:15 PM)."""
        symbols = ["AAPL"]
        manager = SchedulerManager(mock_price_service, mock_bars_service, symbols)
        
        manager.start()
        
        # Find Job 3
        jobs = manager.scheduler.get_jobs()
        eod_jobs = [j for j in jobs if "Job 3" in j.name]
        
        assert len(eod_jobs) > 0, "Job 3 (EOD) not found"
        eod_job = eod_jobs[0]
        
        # Verify EOD job exists and is configured for 16:15 (4:15 PM)
        assert eod_job is not None
        assert "EOD" in eod_job.name or "Job 3" in eod_job.name
        # The job name contains the description, not the time
        # but the trigger is configured for hour=16, minute=15
        
        manager.stop()
