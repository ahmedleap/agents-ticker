"""Market movers provider and snapshot tests."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.alpaca_service import AlpacaMarketDataError, AlpacaService
from app.services.market_movers_service import MarketMoversService
from app.seed_market_movers import seed_market_movers
from app.models import Instrument, MarketMover


@pytest.mark.parametrize("market_type", ["stocks", "crypto"])
def test_movers_request(market_type):
    service = AlpacaService()
    payload = {"gainers": [], "losers": [], "last_updated": "2026-10-22T14:00:00Z"}
    with patch.object(service, "_make_request", return_value=payload) as request:
        assert service.get_market_movers(market_type) == payload
    request.assert_called_once_with(
        f"/v1beta1/screener/{market_type}/movers", params={"top": 50}
    )


@pytest.mark.parametrize("market_type,top", [("forex", 50), ("stocks", 0), ("crypto", 51)])
def test_movers_rejects_unsupported_request(market_type, top):
    with pytest.raises(ValueError):
        AlpacaService().get_market_movers(market_type, top)


def movers_payload(market, *candidates):
    return {
        "market_type": market,
        "gainers": list(candidates),
        "losers": [],
        "last_updated": "2026-10-22T14:00:00Z",
    }


def candidate(symbol, change, price="100.123456789"):
    return {"symbol": symbol, "price": price, "percent_change": change}


@pytest.fixture
def mover_setup():
    session = MagicMock()
    instruments = [(uuid4(), ticker, "STOCK") for ticker in ["AAPL", "MSFT", "TSLA", "NVDA", "AMD", "GOOG"]]
    instruments.append((uuid4(), "BTC", "CRYPTO"))
    session.query.return_value.filter.return_value.all.return_value = instruments
    alpaca = MagicMock(spec=AlpacaService)
    alpaca.get_market_movers.side_effect = lambda market: movers_payload(
        market, candidate("BTC/USD", "-9")
    ) if market == "crypto" else movers_payload(
        market, candidate("AAPL", "5"), candidate("MSFT", "-5"), candidate("TSLA", "2"),
        candidate("NVDA", "1"), candidate("AMD", "0"), candidate("GOOG", "-3"),
        candidate("UNKNOWN", "99"), candidate("AAPL", "5"), candidate("CADUSD", "100"),
    )
    with patch("app.services.market_movers_service.db_manager.session_scope") as scope:
        scope.return_value.__enter__.return_value = session
        yield MarketMoversService(alpaca), session, scope


def test_refresh_filters_ranks_and_publishes_one_generation(mover_setup):
    service, session, scope = mover_setup
    assert service.refresh() == 5
    records = [call.args[0] for call in session.add.call_args_list]
    assert [record.change_percent for record in records] == list(map(Decimal, ["-9", "5", "-5", "-3", "2"]))
    assert [record.rank for record in records] == [1, 2, 3, 4, 5]
    assert len({record.snapshot_id for record in records}) == 1
    assert len({record.refreshed_at for record in records}) == 1
    assert records[0].price == Decimal("100.123456789")
    assert records[0].source_as_of == datetime(2026, 10, 22, 14, tzinfo=timezone.utc)
    session.query.return_value.delete.assert_called_once_with(synchronize_session=False)
    assert scope.call_count == 2


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity", None, "bad", "1e16"])
def test_refresh_skips_invalid_numbers(mover_setup, invalid):
    service, session, _ = mover_setup
    service.alpaca.get_market_movers.side_effect = lambda market: movers_payload(
        market, candidate("AAPL", invalid), candidate("MSFT", "0"), candidate("TSLA", "1", "0")
    )
    assert service.refresh() == 1
    assert session.add.call_args.args[0].change_percent == Decimal("0")


@pytest.mark.parametrize("payload", [None, {}, {"gainers": [], "losers": []},
    {"market_type": "crypto", "gainers": [], "losers": [], "last_updated": "bad"},
    {"market_type": "crypto", "gainers": [], "losers": [], "last_updated": "2026-10-22T14:00:00"}])
def test_refresh_rejects_malformed_response_without_deleting(mover_setup, payload):
    service, session, _ = mover_setup
    service.alpaca.get_market_movers.side_effect = None
    service.alpaca.get_market_movers.return_value = payload
    with pytest.raises(AlpacaMarketDataError):
        service.refresh()
    session.query.return_value.delete.assert_not_called()
    session.add.assert_not_called()


def test_second_market_failure_does_not_publish_partial_snapshot(mover_setup):
    service, session, _ = mover_setup
    service.alpaca.get_market_movers.side_effect = [movers_payload("crypto", candidate("BTC/USD", "9")), AlpacaMarketDataError("unavailable")]
    with pytest.raises(AlpacaMarketDataError):
        service.refresh()
    session.query.return_value.delete.assert_not_called()


def test_successful_empty_response_clears_snapshot(mover_setup):
    service, session, _ = mover_setup
    service.alpaca.get_market_movers.side_effect = lambda market: movers_payload(market)
    assert service.refresh() == 0
    session.query.return_value.delete.assert_called_once()
    session.add.assert_not_called()


def test_crypto_does_not_match_non_usd_pair(mover_setup):
    service, session, _ = mover_setup
    service.alpaca.get_market_movers.side_effect = lambda market: movers_payload(market, candidate("BTC/USDT", "10"))
    assert service.refresh() == 0
    session.add.assert_not_called()


@pytest.mark.parametrize("replace", [False, True])
def test_seed_market_movers_writes_five_demo_rows(replace):
    session = MagicMock()
    session.query.return_value.count.return_value = int(replace)
    instruments = [Instrument(instrument_id=uuid4(), ticker=f"DEMO{index}", asset_class="STOCK") for index in range(5)]
    session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = instruments
    with patch("app.seed_market_movers.db_manager.session_scope") as scope:
        scope.return_value.__enter__.return_value = session
        assert seed_market_movers(replace) == [instrument.ticker for instrument in instruments]
    records = [call.args[0] for call in session.add.call_args_list]
    assert len(records) == 5
    assert all(isinstance(record, MarketMover) for record in records)
    assert [record.rank for record in records] == [1, 2, 3, 4, 5]
    assert [record.change_percent for record in records] == list(map(Decimal, ["-5", "4", "-3", "2", "-1"]))
    assert all(record.price == Decimal("100") for record in records)
    assert len({record.snapshot_id for record in records}) == 1


def test_seed_market_movers_preserves_existing_snapshot_by_default():
    session = MagicMock()
    session.query.return_value.count.return_value = 5
    with patch("app.seed_market_movers.db_manager.session_scope") as scope:
        scope.return_value.__enter__.return_value = session
        with pytest.raises(ValueError, match="already exists"):
            seed_market_movers()
    session.query.return_value.delete.assert_not_called()
    session.add.assert_not_called()


def test_seed_market_movers_preserves_snapshot_when_universe_too_small():
    session = MagicMock()
    session.query.return_value.count.return_value = 0
    session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    with patch("app.seed_market_movers.db_manager.session_scope") as scope:
        scope.return_value.__enter__.return_value = session
        with pytest.raises(ValueError, match="At least five"):
            seed_market_movers()
    session.query.return_value.delete.assert_not_called()