"""SQLAlchemy database models for market data service."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Numeric, FetchedValue, Integer, ForeignKey, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid as uuid_lib

Base = declarative_base()


class MarketMover(Base):
    """Latest atomically published provider-calculated movers snapshot."""
    __tablename__ = "market_movers"

    rank = Column(Integer, primary_key=True, autoincrement=False)
    instrument_id = Column(UUID(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False, unique=True)
    snapshot_id = Column(UUID(as_uuid=True), nullable=False)
    price = Column(Numeric(28, 12), nullable=False)
    change_percent = Column(Numeric(28, 12), nullable=False)
    source_market = Column(String(6), nullable=False)
    source_as_of = Column(DateTime(timezone=True), nullable=False)
    refreshed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("rank BETWEEN 1 AND 5", name="market_movers_rank_check"),
        CheckConstraint("price > 0 AND price < 10000000000000000", name="market_movers_price_check"),
        CheckConstraint("change_percent > -10000000000000000 AND change_percent < 10000000000000000", name="market_movers_change_check"),
        CheckConstraint("source_market IN ('stocks', 'crypto')", name="market_movers_market_check"),
    )


class Instrument(Base):
    """Represents a financial instrument (stock, ETF, etc.) with real-time pricing."""
    __tablename__ = "instruments"

    instrument_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    asset_class = Column(String(50), nullable=False)
    industry = Column(String(100))
    
    # Real-time pricing (updated by market data service every ~10 seconds)
    bid = Column(Numeric(18, 4), nullable=True)
    ask = Column(Numeric(18, 4), nullable=True)
    # mid_price is GENERATED ALWAYS by PostgreSQL - tell SQLAlchemy to fetch it, not insert
    mid_price = Column(Numeric(18, 4), server_default=FetchedValue())
    price_updated_at = Column(DateTime, nullable=True)
    
    # Relationship to price history
    price_history = relationship("InstrumentPriceHistory", back_populates="instrument", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Instrument(ticker='{self.ticker}', name='{self.name}', bid={self.bid}, ask={self.ask})>"


class InstrumentPriceHistory(Base):
    """Historical OHLC price data for instruments."""
    __tablename__ = "instrument_price_history"
    
    price_history_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4)
    instrument_id = Column(UUID(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    
    # OHLC data
    open = Column(Numeric(18, 4), nullable=False)
    high = Column(Numeric(18, 4), nullable=False)
    low = Column(Numeric(18, 4), nullable=False)
    close = Column(Numeric(18, 4), nullable=False)
    volume = Column(Integer, nullable=False, default=0)
    
    # Relationship back to instrument
    instrument = relationship("Instrument", back_populates="price_history")
    
    # Composite index for efficient queries by instrument and time
    __table_args__ = (
        Index("ix_instrument_price_history_instrument_timestamp", "instrument_id", "timestamp", unique=False),
    )
    
    def __repr__(self):
        return f"<InstrumentPriceHistory(instrument_id={self.instrument_id}, timestamp={self.timestamp}, close={self.close})>"
