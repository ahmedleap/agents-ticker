"""SQLAlchemy database models for market data service."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Numeric, FetchedValue
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
import uuid as uuid_lib

Base = declarative_base()


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

    def __repr__(self):
        return f"<Instrument(ticker='{self.ticker}', name='{self.name}', bid={self.bid}, ask={self.ask})>"
