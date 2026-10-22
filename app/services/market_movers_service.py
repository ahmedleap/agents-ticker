"""Publish a database-filtered snapshot of Alpaca stock and crypto movers."""
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.database import db_manager
from app.models import Instrument, MarketMover
from app.services.alpaca_service import AlpacaMarketDataError, AlpacaService

logger = logging.getLogger(__name__)


class MarketMoversService:
    def __init__(self, alpaca_service: AlpacaService):
        self.alpaca = alpaca_service

    @staticmethod
    def _provider_symbol(ticker: str, market: str) -> str:
        ticker = ticker.upper()
        if market == "crypto" and "/" not in ticker:
            return f"{ticker}/USD"
        return ticker

    def refresh(self) -> int:
        """Replace the complete snapshot, or raise without publishing any changes."""
        with db_manager.session_scope() as session:
            instruments = session.query(
                Instrument.instrument_id, Instrument.ticker, Instrument.asset_class
            ).filter(Instrument.asset_class.in_(["STOCK", "CRYPTO"])).all()

        universe = {}
        for instrument_id, ticker, asset_class in instruments:
            market = "crypto" if asset_class == "CRYPTO" else "stocks"
            universe[(market, self._provider_symbol(ticker, market))] = (instrument_id, ticker)

        selected = {}
        for market in sorted({key[0] for key in universe}):
            payload = self.alpaca.get_market_movers(market)
            if (
                not isinstance(payload, dict)
                or payload.get("market_type") != market
                or not isinstance(payload.get("gainers"), list)
                or not isinstance(payload.get("losers"), list)
            ):
                raise AlpacaMarketDataError(f"Invalid {market} movers response")
            try:
                source_as_of = datetime.fromisoformat(payload["last_updated"].replace("Z", "+00:00"))
                if source_as_of.utcoffset() is None:
                    raise ValueError("Missing timestamp offset")
                source_as_of = source_as_of.astimezone(timezone.utc)
            except (KeyError, TypeError, AttributeError, ValueError) as exc:
                raise AlpacaMarketDataError(f"Invalid {market} movers timestamp") from exc

            for candidate in payload["gainers"] + payload["losers"]:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("symbol"), str):
                    continue
                instrument = universe.get((market, candidate["symbol"].upper()))
                if instrument is None:
                    continue
                try:
                    price = Decimal(str(candidate["price"]))
                    change_percent = Decimal(str(candidate["percent_change"]))
                    if (
                        not price.is_finite()
                        or not change_percent.is_finite()
                        or not Decimal("0.000000000001") <= price < Decimal("1e16")
                        or abs(change_percent) >= Decimal("1e16")
                    ):
                        continue
                except (KeyError, InvalidOperation, TypeError, ValueError):
                    continue
                instrument_id, ticker = instrument
                record = {
                    "instrument_id": instrument_id,
                    "ticker": ticker,
                    "price": price,
                    "change_percent": change_percent,
                    "source_market": market,
                    "source_as_of": source_as_of,
                }
                previous = selected.get(instrument_id)
                if previous is None or abs(change_percent) > abs(previous["change_percent"]):
                    selected[instrument_id] = record

        movers = sorted(
            selected.values(),
            key=lambda record: (-abs(record["change_percent"]), record["ticker"], str(record["instrument_id"])),
        )[:5]
        snapshot_id = uuid4()
        refreshed_at = datetime.now(timezone.utc)
        with db_manager.session_scope() as session:
            session.query(MarketMover).delete(synchronize_session=False)
            for rank, record in enumerate(movers, start=1):
                session.add(MarketMover(
                    rank=rank,
                    instrument_id=record["instrument_id"],
                    snapshot_id=snapshot_id,
                    price=record["price"],
                    change_percent=record["change_percent"],
                    source_market=record["source_market"],
                    source_as_of=record["source_as_of"],
                    refreshed_at=refreshed_at,
                ))
        logger.info("Published market movers: instruments=%s eligible=%s selected=%s", len(universe), len(selected), len(movers))
        return len(movers)