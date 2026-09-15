import asyncio
import time
import unittest
from unittest.mock import patch

from realtime import TradeStream


def batch(*prices):
    return {"ch": "trade", "symbol": "BTCUSDT", "data": [
        {"t": "2026-09-15T19:47:02Z", "p": price, "v": "0.1", "s": "buy"}
        for price in prices]}


class TradeStreamTests(unittest.TestCase):
    def test_batch_and_repeated_trades_are_preserved(self):
        stream = TradeStream()
        stream.connected = True
        stream.accept(batch("75850", "75850", "75852"))
        self.assertEqual(stream.trade_count, 3)
        self.assertEqual(stream.snapshot()["last_trade"]["price"], "75852")
        self.assertEqual(stream.snapshot()["status"], "live")

    def test_invalid_batch_does_not_partially_update(self):
        stream = TradeStream()
        with self.assertRaises(ValueError):
            stream.accept(batch("75850", "NaN"))
        self.assertEqual(stream.trade_count, 0)
        self.assertIsNone(stream.last_trade)

    def test_other_symbol_and_heartbeat_do_not_refresh_trades(self):
        stream = TradeStream()
        message = batch("75850")
        message["symbol"] = "ETHUSDT"
        stream.accept(message)
        stream.accept({"op": "ping", "pong": 123})
        self.assertIsNone(stream.last_received)

    def test_status_distinguishes_stale_and_disconnected(self):
        stream = TradeStream()
        stream.connected = True
        self.assertEqual(stream.snapshot()["status"], "waiting")
        stream.accept(batch("75850"))
        stream.last_received = time.monotonic() - 20
        self.assertEqual(stream.snapshot()["status"], "stale")
        stream.connected = False
        self.assertEqual(stream.snapshot()["status"], "disconnected")


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_retry_stops_task(self):
        stream = TradeStream()
        with patch("realtime.connect", side_effect=OSError("offline")):
            task = asyncio.create_task(stream.run())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(stream.connected)
        self.assertIn("offline", stream.last_error)
