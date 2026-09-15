"""Public Bitunix market data, validation and candle normalization."""

import json
import logging
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = "https://fapi.bitunix.com/api/v1/futures/market"
logger = logging.getLogger("uvicorn.error")
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


class MarketDataError(Exception):
    """An upstream failure or invalid upstream data."""


class InstrumentNotFound(Exception):
    """The requested symbol is not an active USDT instrument."""


def iso_time(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat()


def decimal_value(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a market value")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Non-finite market value")
    return number


def normalize_candles(
    rows: list[dict], interval: str, as_of_ms: int,
    previous_candle: dict | None = None,
) -> list[dict]:
    """Sort candles and estimate closure using the request start time.

    Bitunix kline volume names are reversed relative to its ticker endpoint.
    Mapping is based on observed responses; VWAP is checked against OHLC.
    """
    duration = INTERVAL_MS[interval]
    candles = {}
    row = {}
    try:
        for row in sorted(rows, key=lambda item: int(item["time"])):
            timestamp_value = row["time"]
            if isinstance(timestamp_value, bool) or not re.fullmatch(r"[0-9]+", str(timestamp_value)):
                raise ValueError("Invalid timestamp")
            timestamp = int(timestamp_value)
            if timestamp <= 0 or timestamp % duration != 0 or timestamp > as_of_ms:
                raise ValueError("Unaligned or future timestamp")
            opening, high, low, close = [decimal_value(row[key]) for key in ("open", "high", "low", "close")]
            if low <= 0 or opening <= 0 or not low <= close <= high:
                raise ValueError("Invalid OHLC range")
            warnings = []
            if not low <= opening <= high:
                previous = candles.get(timestamp - duration, previous_candle)
                if (previous is None
                        or previous["open_time_ms"] != timestamp - duration
                        or Decimal(previous["close"]) != opening):
                    raise ValueError("Open outside range without matching previous close")
                # Observed Bitunix convention, not a documented guarantee.
                # Preserve raw prices; this candle is not standard OHLC.
                warnings.append("open_outside_range_matches_previous_close")
            # Confirmed on the kline response supplied during integration.
            volume_base = decimal_value(row["quoteVol"])
            volume_quote = decimal_value(row["baseVol"])
            if volume_base < 0 or volume_quote < 0:
                raise ValueError("Negative volume")
            if (volume_base == 0) != (volume_quote == 0):
                raise ValueError("Inconsistent zero volumes")
            if volume_base > 0:
                average_price = volume_quote / volume_base
                # Allow a small tolerance for rounding of reported volumes.
                tolerance = high * Decimal("0.001")
                if not low - tolerance <= average_price <= high + tolerance:
                    raise ValueError("Candle volume units are inconsistent with prices")
            candle = {
                "open_time_ms": timestamp,
                "open_time": iso_time(timestamp),
                "close_time_ms": timestamp + duration,
                "open": str(opening), "high": str(high),
                "low": str(low), "close": str(close),
                "volume_base": str(volume_base),
                "volume_quote": str(volume_quote),
                "is_closed": timestamp + duration <= as_of_ms,
                "warnings": warnings,
            }
            if timestamp in candles and candles[timestamp] != candle:
                raise ValueError("Conflicting duplicate candles")
            candles[timestamp] = candle
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError, OSError) as exc:
        logger.warning(
            "Bitunix candle validation failed: %s; interval=%s; as_of_ms=%s; candle=%r",
            exc, interval, as_of_ms, row,
        )
        raise MarketDataError("Bitunix вернул некорректные свечи; расчёт остановлен") from exc
    return [candles[timestamp] for timestamp in sorted(candles)]


class BitunixMarketDataService:
    def fetch_rows(self, endpoint: str, params: dict | None = None) -> list[dict]:
        url = f"{BASE_URL}/{endpoint}"
        if params:
            url += "?" + urlencode(params)
        try:
            with urlopen(url, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as exc:
            message = "Bitunix ограничил частоту запросов" if exc.code == 429 else "Bitunix вернул ошибку HTTP"
            raise MarketDataError(message) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MarketDataError("Не удалось получить ответ от Bitunix") from exc
        except (ValueError, UnicodeError) as exc:
            raise MarketDataError("Bitunix вернул некорректный JSON") from exc
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise MarketDataError("Bitunix сообщил об ошибке запроса")
        rows = payload.get("data")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise MarketDataError("Bitunix вернул некорректный список данных")
        return rows

    def get_active_usdt_futures(self) -> list[dict]:
        instruments = {}
        for pair in self.fetch_rows("trading_pairs"):
            if pair.get("quote") != "USDT" or pair.get("symbolStatus") != "OPEN":
                continue
            symbol, base = pair.get("symbol"), pair.get("base")
            if not isinstance(symbol, str) or not symbol or not isinstance(base, str) or not base:
                raise MarketDataError("Bitunix вернул инструмент без символа или базовой валюты")
            instruments[symbol] = {"symbol": symbol, "base": base, "quote": "USDT", "status": "OPEN"}
        return [instruments[symbol] for symbol in sorted(instruments)]

    def get_candles(self, symbol: str, interval: str, limit: int, closed_only: bool) -> dict:
        if interval not in INTERVAL_MS or not 1 <= limit <= 400:
            raise ValueError("Unsupported interval or limit")
        instruments = self.get_active_usdt_futures()
        instrument = next((item for item in instruments if item["symbol"] == symbol), None)
        if instrument is None:
            raise InstrumentNotFound("Активный USDT-инструмент не найден")
        as_of_ms = time.time_ns() // 1_000_000
        params = {"symbol": symbol, "interval": interval, "limit": min(limit, 200), "type": "LAST_PRICE"}
        rows = self.fetch_rows("kline", params)
        if limit > 200 and rows:
            try:
                boundary = min(int(row["time"]) for row in rows)
            except (KeyError, ValueError, TypeError) as exc:
                raise MarketDataError("Некорректное время границы истории Bitunix") from exc
            older = self.fetch_rows("kline", {**params, "limit": limit - 200, "endTime": boundary})
            # endTime was observed to be exclusive. Reject unexpected overlap
            # rather than silently accepting an ignored pagination parameter.
            try:
                if any(int(row["time"]) >= boundary for row in older):
                    raise ValueError("Overlapping history pages")
            except (KeyError, ValueError, TypeError) as exc:
                raise MarketDataError("Bitunix вернул некорректную границу исторических свечей") from exc
            rows += older
        valid_rows = []
        rejected_candles = []
        previous_candle = None
        # Invalid timestamps are placed first and rejected by normalization.
        ordered_rows = sorted(rows, key=lambda row: int(str(row.get("time"))) if str(row.get("time", "")).isdigit() else -1)
        for row in ordered_rows:
            try:
                normalized = normalize_candles([row], interval, as_of_ms, previous_candle)
                valid_rows.append(row)
                previous_candle = normalized[0]
            except MarketDataError as exc:
                rejected_candles.append({
                    "source_time": row.get("time"),
                    "reason": str(exc.__cause__ or exc),
                })
        # Batch validation still rejects contradictory duplicates instead of
        # arbitrarily choosing one of two different values for the same minute.
        candles = normalize_candles(valid_rows, interval, as_of_ms)
        gaps = [
            {"after_open_time_ms": left["open_time_ms"], "missing_count": (right["open_time_ms"] - left["open_time_ms"]) // INTERVAL_MS[interval] - 1}
            for left, right in zip(candles, candles[1:])
            if right["open_time_ms"] - left["open_time_ms"] > INTERVAL_MS[interval]
        ]
        items = [candle for candle in candles if candle["is_closed"] or not closed_only]
        warning_count = sum(bool(candle["warnings"]) for candle in items)
        return {
            "exchange": "bitunix", "symbol": symbol, "interval": interval,
            "base_currency": instrument["base"], "quote_currency": "USDT",
            "requested_limit": limit, "received_count": len(rows), "count": len(items),
            "closed_only": closed_only, "as_of": iso_time(as_of_ms),
            "closure_basis": "local_clock_at_request_start",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": "unavailable" if not items else "partial" if rejected_candles or gaps else "warning" if warning_count else "ok",
            "warning_count": warning_count,
            "rejected_count": len(rejected_candles),
            "rejected_candles": rejected_candles,
            "gaps": gaps, "items": items,
        }


market_data = BitunixMarketDataService()
