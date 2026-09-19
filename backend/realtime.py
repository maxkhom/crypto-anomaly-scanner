"""A shared public trade connection owned by the application lifecycle."""
import asyncio
import json
import logging
import time
from pathlib import Path
from history_store import HistoryStore
from anomaly_events import detect_event
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from websockets.asyncio.client import connect
from short_momentum import ShortMomentum
from market import get_market

logger = logging.getLogger(__name__)


class TradeState:
    def __init__(self, symbol="BTCUSDT"):
        self.symbol = symbol
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
        if payload.get("ch") != "trade" or payload.get("symbol") != self.symbol:
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
        self.momentum.add(time.time(), self.last_trade["price"])
        self.last_error = None

    def snapshot(self):
        age = None if self.last_received is None else time.monotonic() - self.last_received
        status = "disconnected" if not self.connected else (
            "waiting" if age is None else "stale" if age > 15 else "live")
        return {"exchange": "bitunix", "symbol": self.symbol, "status": status,
                "connected": self.connected, "last_trade": self.last_trade,
                "seconds_since_last_trade_received": None if age is None else round(age, 2),
                "received_trade_count": self.trade_count,
                "invalid_messages": self.invalid_messages, "reconnects": self.reconnects,
                "last_error": self.last_error,
                "short_momentum": self.momentum.calculate(time.time(), status == "live"),
                "as_of": datetime.now(timezone.utc).isoformat()}

class TradeStream:
    def __init__(self, symbols=("BTCUSDT", "ETHUSDT"), auto_select=False, store=None):
        self.store = store
        self.history_loaded = False
        self.storage_error = None
        self.event_storage_error = None
        self.pending_events = {}
        self.recorded_intervals = {}
        self.auto_select = auto_select
        self.selected_at = None
        self.states = {symbol: TradeState(symbol) for symbol in symbols}
        self.connected = False
        self.reconnects = 0
        self.last_error = None

    async def restore_history(self):
        if not self.store or self.history_loaded:
            return
        try:
            saved = await asyncio.to_thread(self.store.load, time.time())
            for symbol, state in self.states.items():
                item = saved.get(symbol)
                if item and item["rows"]:
                    state.momentum.started = item["started"]
                    state.momentum.boundaries.extend(item["rows"])
                    state.momentum.next_boundary = item["rows"][-1][0] + 10
                    state.momentum.advance(time.time())
            self.storage_error = None
        except Exception as exc:
            self.storage_error = str(exc)
            logger.warning("Cannot restore price history: %s", exc)
        self.history_loaded = True

    async def save_history(self):
        if not self.store or not self.history_loaded:
            return
        now = time.time()
        snapshots = []
        for symbol, state in self.states.items():
            state.momentum.advance(now)
            snapshots.append((symbol, state.momentum.started, [
                (stamp, None if price is None else str(price))
                for stamp, price in state.momentum.boundaries]))
        try:
            await asyncio.to_thread(self.store.save, snapshots, now)
            self.storage_error = None
        except Exception as exc:
            self.storage_error = str(exc)
            logger.warning("Cannot save price history: %s", exc)

    async def record_events(self):
        if not self.store or not self.history_loaded:
            return
        now, monotonic_now = time.time(), time.monotonic()
        for symbol, state in self.states.items():
            live = self.connected and state.last_received is not None and monotonic_now - state.last_received <= 15
            event = detect_event(symbol, state.momentum, now, live,
                                 state.last_trade['price'] if state.last_trade else None)
            if event and self.recorded_intervals.get(symbol) != event['interval_end']:
                self.pending_events.setdefault((symbol, event['interval_end']), event)
        try:
            events = list(self.pending_events.values())
            if events:
                await asyncio.to_thread(self.store.save_events, events)
                for event in events:
                    self.recorded_intervals[event['symbol']] = event['interval_end']
                self.pending_events.clear()
            self.event_storage_error = None
        except Exception as exc:
            self.event_storage_error = str(exc)
            logger.warning('Cannot save anomaly events: %s', exc)

    async def persist_history(self, stop):
        next_save = 0
        while not stop.is_set():
            await self.record_events()
            if time.monotonic() >= next_save:
                await self.save_history()
                next_save = time.monotonic() + 10
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
        await self.record_events()
        await self.save_history()

    def select_symbols(self, market):
        # get_market has already validated active contracts, prices and volumes.
        ordered = sorted(market["items"],
                         key=lambda item: (-Decimal(item["volume_24h_usdt"]), item["symbol"]))
        symbols = list(dict.fromkeys(item["symbol"] for item in ordered))[:20]
        if not symbols:
            raise ValueError("Нет доступных контрактов для потока")
        self.states = {symbol: TradeState(symbol) for symbol in symbols}
        self.selected_at = market["fetched_at"]

    def overview(self, include_items=False):
        items = [self.snapshot(symbol) for symbol in self.states]
        return {"symbols": list(self.states), "count": len(items),
                "live_count": sum(item["status"] == "live" for item in items),
                "connected": self.connected, "selected_at": self.selected_at,
                "selection": "top_20_by_24h_quote_volume_at_startup",
                "last_error": self.last_error, "storage_error": self.storage_error or self.event_storage_error,
                **({"items": items} if include_items else {})}

    def snapshot(self, symbol="BTCUSDT"):
        state = self.states[symbol]
        state.connected = self.connected
        state.reconnects = self.reconnects
        result = state.snapshot()
        result["last_error"] = self.last_error
        result["subscribed_symbols"] = list(self.states)
        return result

    def reset_history(self):
        for state in self.states.values():
            state.last_received = None
            state.last_trade = None
            state.momentum.last_sample = None
            state.momentum.advance(time.time())

    def accept(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
        if payload.get("ch") != "trade":
            return False
        state = self.states.get(payload.get("symbol"))
        if state is None:
            return False
        try:
            state.accept(payload)
        except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
            state.invalid_messages += 1
            state.momentum.last_sample = None
            return False
        self.last_error = None
        return True

    async def run(self):
        delay = 1
        try:
            while True:
                try:
                    if self.auto_select and not self.states:
                        self.select_symbols(await asyncio.to_thread(get_market))
                    await self.restore_history()
                    async with connect("wss://fapi.bitunix.com/public/", open_timeout=10,
                                       close_timeout=3, ping_interval=None) as socket:
                        self.connected = True
                        self.reset_history()
                        await socket.send(json.dumps({"op": "subscribe", "args": [
                            {"symbol": symbol, "ch": "trade"} for symbol in self.states]}))
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
                            try:
                                received = self.accept(json.loads(raw))
                            except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
                                for state in self.states.values():
                                    state.invalid_messages += 1
                                    state.momentum.last_sample = None
                                continue
                            if received:
                                delay = 1
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning("Bitunix WebSocket disconnected: %s", self.last_error)
                finally:
                    self.connected = False
                    for state in self.states.values():
                        state.momentum.last_sample = None
                await asyncio.sleep(delay)
                self.reconnects += 1
                delay = min(delay * 2, 30)
        finally:
            self.connected = False


trade_stream = TradeStream(symbols=(), auto_select=True,
                           store=HistoryStore(Path(__file__).resolve().parent / "data" / "scanner.sqlite3"))
