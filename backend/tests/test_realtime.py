import asyncio
import time
import unittest
from unittest.mock import patch

from realtime import TradeState, TradeStream


def batch(*prices):
    return {"ch": "trade", "symbol": "BTCUSDT", "data": [
        {"t": "2026-09-15T19:47:02Z", "p": price, "v": "0.1", "s": "buy"}
        for price in prices]}


class TradeStreamTests(unittest.TestCase):
    def test_batch_and_repeated_trades_are_preserved(self):
        stream = TradeState()
        stream.connected = True
        stream.accept(batch("75850", "75850", "75852"))
        self.assertEqual(stream.trade_count, 3)
        self.assertEqual(stream.snapshot()["last_trade"]["price"], "75852")
        self.assertEqual(stream.snapshot()["status"], "live")

    def test_invalid_batch_does_not_partially_update(self):
        stream = TradeState()
        with self.assertRaises(ValueError):
            stream.accept(batch("75850", "NaN"))
        self.assertEqual(stream.trade_count, 0)
        self.assertIsNone(stream.last_trade)

    def test_other_symbol_and_heartbeat_do_not_refresh_trades(self):
        stream = TradeState()
        message = batch("75850")
        message["symbol"] = "ETHUSDT"
        stream.accept(message)
        stream.accept({"op": "ping", "pong": 123})
        self.assertIsNone(stream.last_received)

    def test_status_distinguishes_stale_and_disconnected(self):
        stream = TradeState()
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


class MultiSymbolTests(unittest.TestCase):
    def test_prices_and_freshness_are_independent(self):
        stream = TradeStream()
        stream.connected = True
        stream.accept(batch("75000"))
        eth = batch("2400", "2401")
        eth["symbol"] = "ETHUSDT"
        stream.accept(eth)
        stream.states["BTCUSDT"].last_received = time.monotonic() - 20
        btc_result = stream.snapshot("BTCUSDT")
        eth_result = stream.snapshot("ETHUSDT")
        self.assertEqual(btc_result["last_trade"]["price"], "75000")
        self.assertEqual(eth_result["last_trade"]["price"], "2401")
        self.assertEqual(btc_result["received_trade_count"], 1)
        self.assertEqual(eth_result["received_trade_count"], 2)
        self.assertEqual(btc_result["status"], "stale")
        self.assertEqual(eth_result["status"], "live")

    def test_invalid_eth_does_not_reset_btc_history(self):
        stream = TradeStream()
        stream.accept(batch("75000"))
        btc_history = stream.states["BTCUSDT"].momentum
        eth = batch("NaN")
        eth["symbol"] = "ETHUSDT"
        self.assertFalse(stream.accept(eth))
        self.assertIs(stream.states["BTCUSDT"].momentum, btc_history)
        self.assertEqual(stream.states["BTCUSDT"].invalid_messages, 0)
        self.assertEqual(stream.states["ETHUSDT"].invalid_messages, 1)

    def test_reconnect_clears_all_price_histories(self):
        stream = TradeStream()
        for symbol in stream.states:
            message = batch("100")
            message["symbol"] = symbol
            stream.accept(message)
        stream.reset_history()
        for state in stream.states.values():
            self.assertIsNone(state.last_trade)
            self.assertIsNone(state.last_received)
            self.assertIsNone(state.momentum.started)

    def test_unsubscribed_symbol_not_added(self):
        stream = TradeStream()
        message = batch("100")
        message["symbol"] = "SOLUSDT"
        self.assertFalse(stream.accept(message))
        self.assertNotIn("SOLUSDT", stream.states)


class UniverseTests(unittest.TestCase):
    def test_selects_twenty_by_numeric_volume(self):
        stream = TradeStream(symbols=(), auto_select=True)
        market = {"fetched_at": "2026-09-16T00:00:00+00:00", "items": [
            {"symbol": f"COIN{i}USDT", "volume_24h_usdt": str(i)} for i in range(25)]}
        stream.select_symbols(market)
        self.assertEqual(len(stream.states), 20)
        self.assertEqual(list(stream.states)[0], "COIN24USDT")
        self.assertNotIn("COIN4USDT", stream.states)
        self.assertEqual(stream.overview()["live_count"], 0)
        self.assertEqual(stream.selected_at, market["fetched_at"])

    def test_empty_selection_fails_instead_of_silent_connection(self):
        stream = TradeStream(symbols=())
        with self.assertRaises(ValueError):
            stream.select_symbols({"items": [], "fetched_at": "now"})
        self.assertEqual(stream.overview()["symbols"], [])

    def test_fewer_than_twenty_and_ties(self):
        stream = TradeStream(symbols=())
        stream.select_symbols({"fetched_at": "now", "items": [
            {"symbol": "ETHUSDT", "volume_24h_usdt": "100"},
            {"symbol": "BTCUSDT", "volume_24h_usdt": "100"}]})
        self.assertEqual(list(stream.states), ["BTCUSDT", "ETHUSDT"])


class BatchSnapshotTests(unittest.TestCase):
    def test_batch_contains_independent_states_without_upstream_requests(self):
        stream = TradeStream()
        stream.connected = True
        stream.accept(batch("75000"))
        with patch("realtime.get_market", side_effect=AssertionError("Unexpected network call")):
            result = stream.overview(include_items=True)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["live_count"], 1)
        rows = {item["symbol"]: item for item in result["items"]}
        self.assertEqual(rows["BTCUSDT"]["last_trade"]["price"], "75000")
        self.assertEqual(rows["ETHUSDT"]["status"], "waiting")
        stream.connected = False
        self.assertTrue(all(item["status"] == "disconnected" for item in stream.overview(True)["items"]))
        self.assertNotIn("items", stream.overview())
