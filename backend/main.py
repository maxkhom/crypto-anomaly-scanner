from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from bitunix import InstrumentNotFound, MarketDataError, market_data
from market import get_market
from price_changes import calculate_price_changes
from relative_volume import calculate_relative_volume

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


@app.get("/api/scanner/price-changes")
def price_changes(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
) -> dict:
    source = market_data.get_candles(symbol, "1m", 243, True)
    as_of_ms = int(datetime.fromisoformat(source["as_of"]).timestamp() * 1000)
    result = calculate_price_changes(source["items"], as_of_ms)
    return {
        "exchange": "bitunix", "symbol": symbol,
        "as_of": source["as_of"], "fetched_at": source["fetched_at"],
        "source_quality": source["data_quality"],
        "source_rejected_count": source["rejected_count"],
        "closure_basis": source["closure_basis"],
        **result,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "crypto-anomaly-scanner"}


@app.get("/api/scanner/metrics")
def scanner_metrics(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
) -> dict:
    source = market_data.get_candles(symbol, "1m", 243, True)
    as_of_ms = int(datetime.fromisoformat(source["as_of"]).timestamp() * 1000)
    return {
        "exchange": "bitunix", "symbol": symbol,
        "as_of": source["as_of"], "fetched_at": source["fetched_at"],
        "source_quality": source["data_quality"],
        "source_rejected_count": source["rejected_count"],
        "closure_basis": source["closure_basis"],
        **calculate_price_changes(source["items"], as_of_ms),
        "relative_volume": calculate_relative_volume(source["items"], as_of_ms),
    }


@app.get("/api/scanner/relative-volume")
def relative_volume(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
) -> dict:
    # Two extra rows allow for the current minute and predecessor validation.
    source = market_data.get_candles(symbol, "1m", 107, True)
    as_of_ms = int(datetime.fromisoformat(source["as_of"]).timestamp() * 1000)
    return {
        "exchange": "bitunix", "symbol": symbol,
        "as_of": source["as_of"], "fetched_at": source["fetched_at"],
        "source_quality": source["data_quality"],
        "source_rejected_count": source["rejected_count"],
        "closure_basis": source["closure_basis"],
        **calculate_relative_volume(source["items"], as_of_ms),
    }


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
