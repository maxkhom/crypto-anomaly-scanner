import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch

from history_store import HistoryStore
from realtime import TradeStream


class StoreTests(unittest.TestCase):
    def test_roundtrip_missing_prices_and_idempotent_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.sqlite3'
            store = HistoryStore(path)
            rows = [('BTCUSDT', 0, [(10, '100.123456789'), (20, None), (30, '110')])]
            store.save(rows, 31)
            store.save(rows, 31)
            saved = HistoryStore(path).load(31)['BTCUSDT']['rows']
            self.assertEqual(saved, [(10, Decimal('100.123456789')), (20, None), (30, Decimal('110'))])
            self.assertEqual(store.load(4000), {})
            store.save([], 4000)
            with store.connection() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM receipt_boundaries_v1').fetchone()[0], 0)


class RestoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_preserves_old_boundaries_and_marks_downtime_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            store = HistoryStore(Path(folder) / 'history.sqlite3')
            store.save([('BTCUSDT', 0, [(10, '100'), (20, '101'), (30, '102')])], 31)
            stream = TradeStream(symbols=('BTCUSDT',), store=store)
            with patch('realtime.time.time', return_value=55):
                await stream.restore_history()
                stream.reset_history()
                momentum = stream.states['BTCUSDT'].momentum
                self.assertEqual(dict(momentum.boundaries)[20], Decimal('101'))
                self.assertIsNone(dict(momentum.boundaries)[40])
                self.assertIsNone(dict(momentum.boundaries)[50])
                self.assertIsNone(momentum.last_sample)
                self.assertFalse(stream.snapshot()['connected'])
                await stream.save_history()
            self.assertEqual(len(store.load(55)['BTCUSDT']['rows']), 5)
