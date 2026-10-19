from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.alpaca_service import AlpacaService
from app.services.bars_service import BarsService
from app.bootstrap_instruments import load_industry_mapping
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


def test_alpaca_crypto_bars_use_crypto_endpoint():
    service = AlpacaService()
    with patch.object(
        service,
        "_make_request",
        return_value={"bars": {"BTC/USD": [{"t": "2026-01-02T00:00:00Z"}]}},
    ) as request:
        bars = service.get_crypto_bars("BTC", "2025-01-01", "2026-01-01")

    assert bars == [{"t": "2026-01-02T00:00:00Z"}]
    request.assert_called_once_with(
        "/v1beta3/crypto/us/bars",
        params={
            "symbols": "BTC/USD",
            "start": "2025-01-01",
            "end": "2026-01-01",
            "timeframe": "1Day",
            "limit": 10000,
        },
    )


def test_forex_historical_rates_become_synthetic_daily_bars():
    service = ForexService(url="https://example.test/rates")
    with patch("app.services.forex_service.requests.get") as get:
        response = MagicMock()
        response.json.return_value = [
            {"base": "CAD", "quote": "USD", "rate": 1.25, "date": "2026-01-02"},
            {"base": "CAD", "quote": "USD", "rate": 1.25, "date": "2026-01-03"},
        ]
        get.return_value = response

        bars = service.get_historical_bars("CADUSD", "2026-01-01", "2026-01-03")

    assert len(bars) == 1
    assert bars[0]["o"] == Decimal("1.25")
    assert bars[0]["h"] == bars[0]["l"] == bars[0]["c"] == Decimal("1.25")
    assert bars[0]["v"] == 0
    get.assert_called_once_with(
        "https://example.test/rates",
        params={
            "base": "CAD",
            "quotes": "USD",
            "from": "2026-01-01",
            "to": "2026-01-03",
        },
        timeout=30,
    )


def test_bars_service_routes_by_asset_class():
    alpaca = MagicMock()
    forex = MagicMock()
    service = BarsService(alpaca, forex)

    service._get_bars("STOCK", "AAPL", "2026-01-01", "2026-01-02")
    service._get_bars("CRYPTO", "BTC", "2026-01-01", "2026-01-02")
    service._get_bars("FOREX", "CADUSD", "2026-01-01", "2026-01-02")

    alpaca.get_bars.assert_called_once_with("AAPL", "2026-01-01", "2026-01-02")
    alpaca.get_crypto_bars.assert_called_once_with("BTC", "2026-01-01", "2026-01-02")
    forex.get_historical_bars.assert_called_once_with(
        "CADUSD", "2026-01-01", "2026-01-02"
    )


def test_asset_class_is_used_for_new_instruments():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    service = PriceService(MagicMock())

    instrument = service.get_or_create_instrument(session, "BTC", "CRYPTO")

    assert instrument.asset_class == "CRYPTO"
    assert instrument.ticker == "BTC"


def test_sp500_industry_mapping_covers_repository_universe():
    mapping = load_industry_mapping()

    assert len(mapping) == 469
    assert mapping["AAPL"] == "Technology Hardware, Storage & Peripherals"
    assert mapping["BRK.B"] == "Multi-Sector Holdings"
    assert mapping["DOW"] == "Commodity Chemicals"


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


def test_eod_job_iterates_all_asset_symbols():
    price_service = MagicMock()
    bars_service = MagicMock()
    bars_service.load_eod_bar.return_value = {"success": True, "errors": []}
    manager = SchedulerManager(
        price_service,
        bars_service,
        ["AAPL"],
        eod_symbols=["AAPL", "BTC", "CADUSD"],
    )

    manager._load_eod_bars()

    assert [call.args[0] for call in bars_service.load_eod_bar.call_args_list] == [
        "AAPL",
        "BTC",
        "CADUSD",
    ]
