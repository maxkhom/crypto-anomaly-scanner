from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from bitunix import InstrumentNotFound, MarketDataError, market_data
from market import get_market

app = FastAPI(title="Crypto Anomaly Scanner")


@app.exception_handler(MarketDataError)
async def market_error_handler(request: Request, exc: MarketDataError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(InstrumentNotFound)
async def instrument_error_handler(request: Request, exc: InstrumentNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/api/market/instruments")
def market_instruments() -> dict:
    items = market_data.get_active_usdt_futures()
    return {"exchange": "bitunix", "count": len(items), "items": items}


@app.get("/api/market/candles")
def market_candles(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
    interval: Literal["1m", "5m", "15m", "1h", "4h"] = "1m",
    limit: int = Query(default=5, ge=1, le=200),
    closed_only: bool = True,
) -> dict:
    return market_data.get_candles(symbol, interval, limit, closed_only)


@app.get("/api/market/tickers")
def market_tickers() -> dict:
    return get_market()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "crypto-anomaly-scanner"}


@app.get("/api/market/ticker")
def market_ticker() -> dict[str, str | float]:
    try:
        ticker = market_data.fetch_rows("tickers", {"symbols": "BTCUSDT"})[0]
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
    except (ValueError, KeyError, IndexError, TypeError, InvalidOperation) as exc:
        raise HTTPException(502, "Bitunix вернул некорректные рыночные данные") from exc
