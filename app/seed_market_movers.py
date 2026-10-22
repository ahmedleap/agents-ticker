"""Seed synthetic market movers for manual API testing, not trading use."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.database import db_manager
from app.models import Instrument, MarketMover


def seed_market_movers(replace: bool = False) -> list[str]:
    """Write five demo rows without changing instruments or historical prices."""
    with db_manager.session_scope() as session:
        if session.query(MarketMover).count() and not replace:
            raise ValueError("Snapshot already exists; use --replace to overwrite it with DEMO data")
        instruments = session.query(Instrument).filter(
            Instrument.asset_class.in_(["STOCK", "CRYPTO"])
        ).order_by(Instrument.ticker).limit(5).all()
        if len(instruments) < 5:
            raise ValueError("At least five existing stock/crypto instruments are required")

        timestamp = datetime.now(timezone.utc)
        snapshot_id = uuid4()
        tickers = [instrument.ticker for instrument in instruments]
        session.query(MarketMover).delete(synchronize_session=False)
        for rank, (instrument, change) in enumerate(
            zip(instruments, ["-5", "4", "-3", "2", "-1"]), start=1
        ):
            price = instrument.mid_price
            if price is None or price <= 0:
                price = Decimal("100")
            session.add(MarketMover(
                rank=rank,
                instrument_id=instrument.instrument_id,
                snapshot_id=snapshot_id,
                price=price,
                change_percent=Decimal(change),
                source_market="crypto" if instrument.asset_class == "CRYPTO" else "stocks",
                source_as_of=timestamp,
                refreshed_at=timestamp,
            ))
    return tickers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true", help="Replace an existing snapshot with DEMO data")
    args = parser.parse_args()
    if not db_manager.initialize():
        return 1
    try:
        tickers = seed_market_movers(args.replace)
        print(f"Seeded {len(tickers)} DEMO movers: {', '.join(tickers)}")
        print("Synthetic changes for endpoint testing only. Live polling replaces these during market hours.")
        return 0
    except Exception as exc:
        print(f"Seeding failed: {exc}")
        print("Apply migrations/003_add_market_movers.sql in pgAdmin before running this script.")
        return 1
    finally:
        db_manager.close()


if __name__ == "__main__":
    raise SystemExit(main())