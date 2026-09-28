"""Tests for Database connection management."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.database import DatabaseManager, db_manager


class TestDatabaseManager:
    """Tests for DatabaseManager."""

    @pytest.fixture
    def manager(self):
        """Create a fresh database manager instance."""
        return DatabaseManager()

    def test_initialization(self, manager):
        """Test database manager initializes correctly."""
        assert manager.engine is None
        assert manager.SessionLocal is None
        assert manager._connected is False

    @patch("app.database.settings")
    def test_initialize_success(self, mock_settings, manager):
        """Test successful database initialization."""
        mock_settings.database_url = "postgresql://test:test@localhost/test_db"
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "test_db"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
            
            result = manager.initialize()
            
            assert result is True
            assert manager._connected is True
            assert manager.engine is not None
            assert manager.SessionLocal is not None

    @patch("app.database.settings")
    def test_initialize_connection_failure(self, mock_settings, manager):
        """Test database initialization handles connection failure."""
        mock_settings.database_url = "postgresql://invalid/url"
        mock_settings.DB_HOST = "invalid"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "invalid"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.side_effect = Exception("Connection failed")
            
            result = manager.initialize()
            
            assert result is False
            assert manager._connected is False

    def test_get_session_not_initialized(self, manager):
        """Test get_session raises error if not initialized."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            manager.get_session()

    @patch("app.database.settings")
    def test_get_session_success(self, mock_settings, manager):
        """Test get_session returns a session after initialization."""
        mock_settings.database_url = "postgresql://test:test@localhost/test_db"
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "test_db"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_session_factory = MagicMock()
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
            
            with patch("app.database.sessionmaker") as mock_sessionmaker:
                mock_sessionmaker.return_value = mock_session_factory
                manager.initialize()
                
                session = manager.get_session()
                assert session == mock_session_factory.return_value

    @patch("app.database.settings")
    def test_session_scope_commit(self, mock_settings, manager):
        """Test session_scope commits on success."""
        mock_settings.database_url = "postgresql://test:test@localhost/test_db"
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "test_db"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_session = MagicMock()
            mock_session_factory = MagicMock(return_value=mock_session)
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
            
            with patch("app.database.sessionmaker") as mock_sessionmaker:
                mock_sessionmaker.return_value = mock_session_factory
                manager.initialize()
                
                with manager.session_scope() as session:
                    pass
                
                mock_session.commit.assert_called_once()
                mock_session.close.assert_called_once()

    @patch("app.database.settings")
    def test_session_scope_rollback_on_error(self, mock_settings, manager):
        """Test session_scope rolls back on error."""
        mock_settings.database_url = "postgresql://test:test@localhost/test_db"
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "test_db"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_session = MagicMock()
            mock_session_factory = MagicMock(return_value=mock_session)
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
            
            with patch("app.database.sessionmaker") as mock_sessionmaker:
                mock_sessionmaker.return_value = mock_session_factory
                manager.initialize()
                
                with pytest.raises(ValueError):
                    with manager.session_scope() as session:
                        raise ValueError("Test error")
                
                mock_session.rollback.assert_called_once()
                mock_session.close.assert_called_once()

    @patch("app.database.settings")
    def test_drop_all_tables(self, mock_settings, manager):
        """Test drop_all_tables removes all tables."""
        mock_settings.database_url = "postgresql://test:test@localhost/test_db"
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "test_db"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
            
            with patch("app.database.sessionmaker"):
                with patch("app.models.Base") as mock_base:
                    mock_metadata = MagicMock()
                    mock_base.metadata = mock_metadata
                    
                    manager.initialize()
                    result = manager.drop_all_tables()
                    
                    assert result is True
                    mock_metadata.drop_all.assert_called_once_with(mock_engine)

    @patch("app.database.settings")
    def test_create_all_tables(self, mock_settings, manager):
        """Test create_all_tables creates all tables."""
        mock_settings.database_url = "postgresql://test:test@localhost/test_db"
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "test_db"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
            
            with patch("app.database.sessionmaker"):
                with patch("app.models.Base") as mock_base:
                    mock_metadata = MagicMock()
                    mock_base.metadata = mock_metadata
                    
                    manager.initialize()
                    result = manager.create_all_tables()
                    
                    assert result is True
                    mock_metadata.create_all.assert_called_once_with(mock_engine)

    @patch("app.database.settings")
    def test_close_connection(self, mock_settings, manager):
        """Test closing database connection."""
        mock_settings.database_url = "postgresql://test:test@localhost/test_db"
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_NAME = "test_db"
        mock_settings.DB_POOL_SIZE = 10
        mock_settings.DB_MAX_OVERFLOW = 20
        mock_settings.DEBUG = False
        mock_settings.REQUEST_TIMEOUT_SECONDS = 30
        mock_settings.SERVICE_NAME = "test_service"
        
        with patch("app.database.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine
            mock_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 1
            
            with patch("app.database.sessionmaker"):
                manager.initialize()
                manager.close()
                
                mock_engine.dispose.assert_called_once()
