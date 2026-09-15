import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import HTTPException

BASE_URL = "https://fapi.bitunix.com/api/v1/futures/market"


def fetch_rows(endpoint: str) -> list[dict]:
    try:
        with urlopen(f"{BASE_URL}/{endpoint}", timeout=10) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise ValueError("Bitunix returned an error")
        rows = payload["data"]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Expected a list of objects")
        return rows
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(502, "Не удалось получить ответ от Bitunix") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "Bitunix вернул некорректный список данных") from exc


def get_market() -> dict:
    pairs = fetch_rows("trading_pairs")
    tickers = fetch_rows("tickers")
    symbols = {
        pair["symbol"]
        for pair in pairs
        if pair.get("quote") == "USDT"
        and pair.get("symbolStatus") == "OPEN"
        and isinstance(pair.get("symbol"), str)
    }
    items = {}
    for ticker in tickers:
        symbol = ticker.get("symbol")
        if not isinstance(symbol, str) or symbol not in symbols:
            continue
        try:
            price = Decimal(ticker["lastPrice"])
            opening = Decimal(ticker["open"])
            volume = Decimal(ticker["quoteVol"])
            if not all(value.is_finite() for value in (price, opening, volume)):
                raise ValueError("Non-finite value")
            if price <= 0 or opening <= 0 or volume < 0:
                raise ValueError("Invalid value")
            items[symbol] = {
                "symbol": symbol,
                "price": str(price),
                "change_24h_pct": round(float((price / opening - 1) * 100), 4),
                "volume_24h_usdt": str(volume),
            }
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue

    ordered = sorted(items.values(), key=lambda item: Decimal(item["volume_24h_usdt"]), reverse=True)
    return {
        "exchange": "bitunix",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "eligible_count": len(symbols),
        "count": len(ordered),
        "unavailable_symbols": sorted(symbols - items.keys()),
        "items": ordered,
    }
