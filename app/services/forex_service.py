"""Frankfurter foreign-exchange quote integration."""
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any, Dict, List

import requests
from requests.exceptions import RequestException, Timeout

from app.config import settings

logger = logging.getLogger(__name__)


class ForexMarketDataError(Exception):
    """Raised when Frankfurter cannot provide a usable rate."""


class ForexService:
    """Fetch reference FX rates and expand them into directed quotes."""

    def __init__(self, url: str | None = None):
        self.url = url or settings.FRANKFURTER_URL
        self.timeout = settings.REQUEST_TIMEOUT_SECONDS

    @staticmethod
    def directed_pairs(currencies: List[str]) -> List[tuple[str, str]]:
        """Return every ordered pair for the configured currencies."""
        normalized = sorted({currency.upper() for currency in currencies})
        return [
            pair
            for first, second in combinations(normalized, 2)
            for pair in ((first, second), (second, first))
        ]

    @staticmethod
    def _extract_rates(payload: Any) -> Dict[tuple[str, str], Decimal]:
        """Normalize supported Frankfurter v2 payload shapes."""
        records = payload if isinstance(payload, list) else [payload]
        rates: Dict[tuple[str, str], Decimal] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            base = str(record.get("base", "")).upper()
            quote = str(record.get("quote", "")).upper()
            if base and quote and "rate" in record:
                try:
                    rates[(base, quote)] = Decimal(str(record["rate"]))
                except (InvalidOperation, TypeError, ValueError):
                    continue
                continue

            base = str(record.get("base", "")).upper()
            for quote, rate in (record.get("rates") or {}).items():
                try:
                    rates[(base, str(quote).upper())] = Decimal(str(rate))
                except (InvalidOperation, TypeError, ValueError):
                    continue
        return rates

    def _fetch(self, base: str, quote: str) -> Decimal:
        try:
            response = requests.get(
                self.url,
                params={"base": base, "quotes": quote},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rates = self._extract_rates(response.json())
            rate = rates.get((base.upper(), quote.upper()))
            if rate is None or rate <= 0:
                raise ForexMarketDataError(f"No positive rate returned for {base}/{quote}")
            return rate
        except Timeout as exc:
            raise ForexMarketDataError(f"Frankfurter timeout for {base}/{quote}") from exc
        except RequestException as exc:
            raise ForexMarketDataError(f"Frankfurter request failed for {base}/{quote}: {exc}") from exc

    def get_quotes(self, currencies: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch canonical rates and return all directed quotes."""
        quotes: Dict[str, Dict[str, Any]] = {}
        timestamp = datetime.now(timezone.utc)
        for base, quote in combinations(sorted({c.upper() for c in currencies}), 2):
            try:
                rate = self._fetch(base, quote)
                forward_bid = rate
                forward_ask = rate
                quotes[f"{base}{quote}"] = {
                    "symbol": f"{base}{quote}",
                    "bid": forward_bid,
                    "ask": forward_ask,
                    "timestamp": timestamp,
                }
                quotes[f"{quote}{base}"] = {
                    "symbol": f"{quote}{base}",
                    "bid": Decimal("1") / forward_ask,
                    "ask": Decimal("1") / forward_bid,
                    "timestamp": timestamp,
                }
            except ForexMarketDataError as exc:
                logger.warning("Skipping FX pair %s/%s: %s", base, quote, exc)
        return quotes

    def get_historical_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, Any]]:
        """Return synthetic daily OHLC bars from Frankfurter reference rates."""
        if len(symbol) != 6:
            raise ForexMarketDataError(f"Invalid compact FX symbol: {symbol}")

        base, quote = symbol[:3].upper(), symbol[3:].upper()
        try:
            response = requests.get(
                self.url,
                params={
                    "base": base,
                    "quotes": quote,
                    "from": start_date,
                    "to": end_date,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            records = response.json()
            if not isinstance(records, list):
                records = [records]

            bars = []
            for record in records:
                if not isinstance(record, dict) or "rate" not in record:
                    continue
                record_date = record.get("date")
                if not record_date:
                    continue
                rate = Decimal(str(record["rate"]))
                if rate <= 0:
                    continue
                timestamp = datetime.combine(
                    date.fromisoformat(record_date),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
                if timestamp.weekday() >= 5:
                    continue
                bars.append({
                    "t": timestamp.isoformat(),
                    "o": rate,
                    "h": rate,
                    "l": rate,
                    "c": rate,
                    "v": 0,
                })
            return bars
        except (Timeout, RequestException) as exc:
            raise ForexMarketDataError(
                f"Frankfurter historical request failed for {symbol}: {exc}"
            ) from exc
