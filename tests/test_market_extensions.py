from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.alpaca_service import AlpacaService
from app.services.forex_service import ForexService
from app.services.price_service import PriceService
from app.services.scheduler import SchedulerManager


def test_forex_quotes_include_exact_inverse_pair():
    service = ForexService(url="https://example.test/rates")
    with patch("app.services.forex_service.requests.get") as get:
        response = MagicMock()
        response.json.return_value = [{"base": "CAD", "quote": "USD", "rate": 1.25}]
        get.return_value = response

        quotes = service.get_quotes(["USD", "CAD"])

    assert quotes["CADUSD"]["bid"] == Decimal("1.25")
    assert quotes["CADUSD"]["ask"] == Decimal("1.25")
    assert quotes["USDCAD"]["bid"] == Decimal("0.8")
    assert quotes["USDCAD"]["ask"] == Decimal("0.8")
    get.assert_called_once_with(
        "https://example.test/rates",
        params={"base": "CAD", "quotes": "USD"},
        timeout=30,
    )


def test_alpaca_crypto_quotes_map_provider_symbols():
    service = AlpacaService()
    with patch.object(
        service,
        "_make_request",
        return_value={"quotes": {"BTC/USD": {"bp": 100, "ap": 101}}},
    ) as request:
        quotes = service.get_latest_crypto_quotes(["BTC"])

    assert quotes == {"BTC": {"bp": 100, "ap": 101}}
    request.assert_called_once_with(
        "/v1beta3/crypto/us/latest/quotes",
        params={"symbols": "BTC/USD"},
    )


def test_asset_class_is_used_for_new_instruments():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    service = PriceService(MagicMock())

    instrument = service.get_or_create_instrument(session, "BTC", "CRYPTO")

    assert instrument.asset_class == "CRYPTO"
    assert instrument.ticker == "BTC"


def test_scheduler_offsets_are_wall_clock_aligned():
    assert SchedulerManager._offset_seconds(0) == "0,10,20,30,40,50"
    assert SchedulerManager._offset_seconds(3) == "3,13,23,33,43,53"
    assert SchedulerManager._offset_seconds(8) == "8,18,28,38,48,58"


def test_scheduler_registers_all_market_cadences():
    manager = SchedulerManager(MagicMock(), MagicMock(), ["AAPL"])
    manager.start()
    try:
        triggers = {
            job.id: str(job.trigger)
            for job in manager.scheduler.get_jobs()
        }
    finally:
        manager.stop()

    assert triggers["market_data_poll_job1"] == "cron[second='0,10,20,30,40,50']"
    assert triggers["forex_poll_job"] == "cron[second='3,13,23,33,43,53']"
    assert triggers["crypto_poll_job"] == "cron[second='8,18,28,38,48,58']"
