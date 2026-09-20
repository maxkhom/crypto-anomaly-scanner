import unittest
import tempfile
from pathlib import Path
from decimal import Decimal

from short_momentum import ShortMomentum
from anomaly_events import detect_event
from history_store import HistoryStore


class EventTests(unittest.TestCase):
    def test_gap_tolerant_baseline_is_versioned_in_events(self):
        data = ShortMomentum()
        data.started = -1
        data.next_boundary = 3010
        data.boundaries.extend((stamp, None if stamp == 1500 else Decimal('110' if stamp == 3000 else '100'))
                               for stamp in range(290, 3001, 10))
        event = detect_event('BTCUSDT', data, 3005, True)
        self.assertEqual(event['rule_version'], 'price_10s_v2')
        self.assertEqual(event['baseline_intervals'], 180)
        self.assertEqual(event['baseline_selection_method'], 'latest_valid_returns')
        self.assertEqual(event['baseline_max_lookback_seconds'], 2700)
        self.assertEqual(event['baseline_skipped_intervals'], 2)
        self.assertEqual(event['percentile'], 100)
        data.boundaries[-1] = (3000, None)
        self.assertIsNone(detect_event('BTCUSDT', data, 3005, True))

    def history(self, final):
        data = ShortMomentum()
        data.started = -1
        data.next_boundary = 1820
        data.boundaries.extend((tick * 10, Decimal('100') if tick < 181 else Decimal(final)) for tick in range(182))
        return data

    def test_inclusive_move_threshold_and_direction(self):
        for price, direction in [('100.1', 'up'), ('99.9', 'down')]:
            event = detect_event('BTCUSDT', self.history(price), 1811, True)
            self.assertEqual(event['direction'], direction)
            self.assertEqual(event['percentile'], 100)
        self.assertIsNone(detect_event('BTCUSDT', self.history('100.09999'), 1811, True))

    def test_missing_history_and_stale_feed_never_create_events(self):
        data = self.history('110')
        self.assertIsNone(detect_event('BTCUSDT', data, 1811, False))
        data.boundaries[5] = (50, None)
        self.assertIsNone(detect_event('BTCUSDT', data, 1811, True))

    def test_common_large_move_is_not_anomaly(self):
        data = self.history('110')
        data.boundaries.clear()
        data.boundaries.extend((tick * 10, Decimal('100') * Decimal('1.01') ** tick) for tick in range(182))
        # All baseline moves exceed the last 0.1% move.
        data.boundaries[-1] = (1810, data.boundaries[-2][1] * Decimal('1.001'))
        self.assertIsNone(detect_event('BTCUSDT', data, 1811, True))

    def test_duplicates_restart_and_history_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.sqlite3'
            store = HistoryStore(path)
            event = detect_event('BTCUSDT', self.history('110'), 1811, True, '111')
            store.save_events([event, event])
            event['detected_at'] = 'changed'
            HistoryStore(path).save_events([event])
            store.save([], 100000)
            result = store.list_events()
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['items'][0]['reference_price'], '111')
            self.assertNotEqual(result['items'][0]['detected_at'], 'changed')
