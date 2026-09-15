from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from bitunix import market_data


def get_market() -> dict:
    pairs = market_data.get_active_usdt_futures()
    tickers = market_data.fetch_rows("tickers")
    symbols = {pair["symbol"] for pair in pairs}
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
