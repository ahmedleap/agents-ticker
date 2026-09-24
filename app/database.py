"""Database connection and session management."""
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, Engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self):
        self.engine: Engine = None
        self.SessionLocal = None
        self._connected = False

    def initialize(self) -> bool:
        """
        Initialize database connection and create engine.
        Returns True if successful, False otherwise.
        """
        try:
            logger.info(
                f"Initializing database connection to {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
            )
            
            self.engine = create_engine(
                settings.database_url,
                poolclass=QueuePool,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                echo=settings.DEBUG,
                connect_args={
                    "connect_timeout": settings.REQUEST_TIMEOUT_SECONDS,
                    "application_name": settings.SERVICE_NAME,
                },
            )
            
            self.SessionLocal = sessionmaker(bind=self.engine)
            
            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self._connected = True
            logger.info("Database connection established successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize database connection: {e}")
            self._connected = False
            return False

    def get_session(self) -> Session:
        """Get a new database session."""
        if not self._connected or self.SessionLocal is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self.SessionLocal()

    @contextmanager
    def session_scope(self):
        """
        Provide a transactional scope for database operations.
        Usage:
            with db_manager.session_scope() as session:
                # perform database operations
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()

    def drop_all_tables(self) -> bool:
        """
        Drop all tables (for reset/testing).
        Returns True if successful, False otherwise.
        """
        try:
            from app.models import Base
            logger.warning("Dropping all tables from database")
            Base.metadata.drop_all(self.engine)
            logger.info("All tables dropped successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to drop tables: {e}")
            return False

    def create_all_tables(self) -> bool:
        """
        Create all tables from models.
        Returns True if successful, False otherwise.
        """
        try:
            from app.models import Base
            logger.info("Creating all tables in database")
            Base.metadata.create_all(self.engine)
            logger.info("All tables created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            return False

    def reset_schema(self) -> bool:
        """
        Drop all tables and recreate them (full reset).
        Returns True if successful, False otherwise.
        """
        try:
            logger.warning("Resetting database schema (drop + create)")
            if not self.drop_all_tables():
                return False
            if not self.create_all_tables():
                return False
            logger.info("Database schema reset completed successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to reset schema: {e}")
            return False

    def close(self):
        """Close database connection."""
        if self.engine:
            self.engine.dispose()
            logger.info("Database connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._connected


# Global database manager instance
db_manager = DatabaseManager()
