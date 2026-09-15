import json
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException

from market import get_market

app = FastAPI(title="Crypto Anomaly Scanner")


@app.get("/api/market/tickers")
def market_tickers() -> dict:
    return get_market()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "crypto-anomaly-scanner"}


@app.get("/api/market/ticker")
def market_ticker() -> dict[str, str | float]:
    url = "https://fapi.bitunix.com/api/v1/futures/market/tickers?symbols=BTCUSDT"
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.load(response)

        if payload["code"] != 0:
            raise ValueError("Bitunix returned an error")

        ticker = payload["data"][0]
        if ticker["symbol"] != "BTCUSDT":
            raise ValueError("Unexpected symbol")

        price = Decimal(ticker["lastPrice"])
        opening_price = Decimal(ticker["open"])
        volume = Decimal(ticker["quoteVol"])
        if not all(value.is_finite() for value in (price, opening_price, volume)):
            raise ValueError("Non-finite market data")
        if price <= 0 or opening_price <= 0 or volume < 0:
            raise ValueError("Invalid market data")

        change = (price / opening_price - 1) * 100
        return {
            "exchange": "bitunix",
            "symbol": "BTCUSDT",
            "price": str(price),
            "change_24h_pct": round(float(change), 4),
            "volume_24h_usdt": str(volume),
        }
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(502, "Не удалось получить ответ от Bitunix") from exc
    except (ValueError, KeyError, IndexError, TypeError, InvalidOperation) as exc:
        raise HTTPException(502, "Bitunix вернул некорректные рыночные данные") from exc
