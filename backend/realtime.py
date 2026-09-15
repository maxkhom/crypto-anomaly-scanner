"""A single public BTC trade connection owned by the application lifecycle."""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from websockets.asyncio.client import connect
from short_momentum import ShortMomentum

logger = logging.getLogger(__name__)


class TradeStream:
    def __init__(self):
        self.connected = False
        self.last_trade = None
        self.last_received = None
        self.trade_count = 0
        self.invalid_messages = 0
        self.reconnects = 0
        self.last_error = None
        self.momentum = ShortMomentum()

    def accept(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
        if payload.get("ch") != "trade" or payload.get("symbol") != "BTCUSDT":
            return
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            raise ValueError("Empty trade batch")
        trades = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid trade")
            price, volume = Decimal(str(row["p"])), Decimal(str(row["v"]))
            stamp = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
            if (not price.is_finite() or not volume.is_finite()
                    or price <= 0 or volume <= 0 or stamp.tzinfo is None
                    or row["s"] not in ("buy", "sell")):
                raise ValueError("Invalid trade values")
            trades.append({"price": str(price), "volume_base": str(volume),
                           "side": row["s"], "time": stamp.isoformat()})
        self.last_trade = trades[-1]
        self.trade_count += len(trades)
        self.last_received = time.monotonic()
        self.momentum.add(self.last_received, self.last_trade["price"])
        self.last_error = None

    def snapshot(self):
        age = None if self.last_received is None else time.monotonic() - self.last_received
        status = "disconnected" if not self.connected else (
            "waiting" if age is None else "stale" if age > 15 else "live")
        return {"exchange": "bitunix", "symbol": "BTCUSDT", "status": status,
                "connected": self.connected, "last_trade": self.last_trade,
                "seconds_since_last_trade_received": None if age is None else round(age, 2),
                "received_trade_count": self.trade_count,
                "invalid_messages": self.invalid_messages, "reconnects": self.reconnects,
                "last_error": self.last_error,
                "short_momentum": self.momentum.calculate(time.monotonic(), status == "live"),
                "as_of": datetime.now(timezone.utc).isoformat()}

    async def run(self):
        delay = 1
        try:
            while True:
                try:
                    async with connect("wss://fapi.bitunix.com/public/", open_timeout=10,
                                       close_timeout=3, ping_interval=None) as socket:
                        self.connected = True
                        self.last_received = None
                        self.last_trade = None
                        self.momentum = ShortMomentum()
                        await socket.send(json.dumps({"op": "subscribe", "args": [
                            {"symbol": "BTCUSDT", "ch": "trade"}]}))
                        next_ping = time.monotonic()
                        last_message = next_ping
                        while True:
                            now = time.monotonic()
                            if now - last_message > 40:
                                raise TimeoutError("Bitunix stream silent for 40 seconds")
                            if now >= next_ping:
                                await socket.send(json.dumps({"op": "ping", "ping": int(time.time())}))
                                next_ping = now + 15
                            try:
                                raw = await asyncio.wait_for(socket.recv(), timeout=5)
                            except TimeoutError:
                                continue
                            last_message = time.monotonic()
                            before = self.trade_count
                            try:
                                self.accept(json.loads(raw))
                            except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
                                self.invalid_messages += 1
                                self.momentum = ShortMomentum()
                                continue
                            if self.trade_count > before:
                                delay = 1
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning("Bitunix WebSocket disconnected: %s", self.last_error)
                finally:
                    self.connected = False
                await asyncio.sleep(delay)
                self.reconnects += 1
                delay = min(delay * 2, 30)
        finally:
            self.connected = False


trade_stream = TradeStream()
