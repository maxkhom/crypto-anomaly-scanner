import asyncio
import os
from pathlib import Path
import sqlite3
from contextlib import asynccontextmanager, suppress
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from bitunix import InstrumentNotFound, MarketDataError, market_data
from market import get_market
from price_changes import calculate_price_changes
from relative_volume import calculate_relative_volume
from minute_momentum import calculate_minute_momentum
from realtime import trade_stream
from open_interest import get_open_interest
from funding import get_funding
from rsi import calculate_rsi
from volatility import calculate_volatility


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_persistence = asyncio.Event()
    persistence = asyncio.create_task(trade_stream.persist_history(stop_persistence))
    task = asyncio.create_task(trade_stream.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        stop_persistence.set()
        await persistence


app = FastAPI(title="Crypto Anomaly Scanner", lifespan=lifespan)


@app.get("/api/scanner/events")
def scanner_events(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    try:
        return trade_stream.store.list_events(limit)
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "История событий временно недоступна") from exc


@app.get("/api/market/realtime/all")
async def realtime_all() -> dict:
    return trade_stream.overview(include_items=True)


@app.get("/api/market/realtime/symbols")
async def realtime_symbols() -> dict:
    return trade_stream.overview()


@app.get("/api/market/realtime")
async def realtime_status(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
) -> dict:
    if symbol not in trade_stream.states:
        raise HTTPException(404, "Поток этой монеты пока не подключён")
    return trade_stream.snapshot(symbol)


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


@app.get("/api/scanner/volatility")
def volatility(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
    interval: Literal["15m", "1h"] = "15m",
) -> dict:
    source = market_data.get_candles(symbol, interval, 102, True)
    as_of_ms = int(datetime.fromisoformat(source["as_of"]).timestamp() * 1000)
    return {"exchange": "bitunix", "symbol": symbol,
            "as_of": source["as_of"], "fetched_at": source["fetched_at"],
            "source_quality": source["data_quality"], "source_rejected_count": source["rejected_count"],
            "closure_basis": source["closure_basis"],
            **calculate_volatility(source["items"], as_of_ms, interval)}


@app.get("/api/scanner/rsi")
def rsi(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
    interval: Literal["15m", "1h"] = "15m",
) -> dict:
    source = market_data.get_candles(symbol, interval, 102, True)
    as_of_ms = int(datetime.fromisoformat(source["as_of"]).timestamp() * 1000)
    return {"exchange": "bitunix", "symbol": symbol,
            "as_of": source["as_of"], "fetched_at": source["fetched_at"],
            "source_quality": source["data_quality"], "source_rejected_count": source["rejected_count"],
            "closure_basis": source["closure_basis"],
            **calculate_rsi(source["items"], as_of_ms, interval)}


@app.get("/api/scanner/funding")
def funding(symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$")) -> dict:
    return get_funding(symbol)


@app.get("/api/scanner/open-interest")
def open_interest(symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$")) -> dict:
    return get_open_interest(symbol)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "crypto-anomaly-scanner"}


@app.get("/api/scanner/metrics")
def scanner_metrics(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
) -> dict:
    source = market_data.get_candles(symbol, "1m", 317, True)
    as_of_ms = int(datetime.fromisoformat(source["as_of"]).timestamp() * 1000)
    return {
        "exchange": "bitunix", "symbol": symbol,
        "as_of": source["as_of"], "fetched_at": source["fetched_at"],
        "source_quality": source["data_quality"],
        "source_rejected_count": source["rejected_count"],
        "closure_basis": source["closure_basis"],
        **calculate_price_changes(source["items"], as_of_ms),
        "relative_volume": calculate_relative_volume(source["items"], as_of_ms),
        "relative_volume_15m": calculate_relative_volume(source["items"], as_of_ms, 15),
        "minute_momentum": calculate_minute_momentum(source["items"], as_of_ms),
    }


@app.get("/api/scanner/relative-volume")
def relative_volume(
    symbol: str = Query(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,40}USDT$"),
    period: Literal["5m", "15m", "1h"] = "5m",
) -> dict:
    # Two extra rows cover the unfinished candle and predecessor validation.
    window_minutes = {"5m": 5, "15m": 15, "1h": 60}[period]
    candle_minutes = 5 if period == "1h" else 1
    source = market_data.get_candles(symbol, f"{candle_minutes}m", window_minutes // candle_minutes * 21 + 2, True)
    as_of_ms = int(datetime.fromisoformat(source["as_of"]).timestamp() * 1000)
    return {
        "exchange": "bitunix", "symbol": symbol,
        "as_of": source["as_of"], "fetched_at": source["fetched_at"],
        "source_quality": source["data_quality"],
        "source_rejected_count": source["rejected_count"],
        "closure_basis": source["closure_basis"],
        **calculate_relative_volume(source["items"], as_of_ms, window_minutes, candle_minutes),
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


# API routes take precedence; only compiled frontend assets are exposed.
frontend_dist = Path(os.environ.get("FRONTEND_DIST") or Path(__file__).resolve().parent.parent / "frontend" / "dist")
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
