import unittest
from decimal import Decimal
from rsi import calculate_rsi, wilder_rsi, INTERVALS


class RSITests(unittest.TestCase):
    def rows(self, interval='15m', mode='up'):
        step = INTERVALS[interval]
        return [{'close_time_ms': (i + 1) * step, 'is_closed': True,
                 'close': str(100 + i if mode == 'up' else 200 - i if mode == 'down' else 100)} for i in range(100)]

    def test_monotonic_and_flat_histories(self):
        for interval in INTERVALS:
            for mode, expected in [('up', 100), ('down', 0), ('flat', 50)]:
                result = calculate_rsi(self.rows(interval, mode), 100 * INTERVALS[interval], interval)
                self.assertEqual(result['rsi'], expected)

    def test_known_wilder_seed_and_next_step(self):
        values = [44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.00]
        closes = [Decimal(str(value)) for value in values]
        self.assertAlmostEqual(float(wilder_rsi(closes[:15])), 70.464135, places=5)
        self.assertAlmostEqual(float(wilder_rsi(closes)), 66.249619, places=5)

    def test_gap_or_unclosed_blocks_calculation(self):
        rows = self.rows()
        rows[40]['is_closed'] = False
        result = calculate_rsi(rows, 90000000, '15m')
        self.assertIsNone(result['rsi'])
        self.assertEqual(result['missing_count'], 1)

    def test_future_excluded_and_invalid_close_rejected(self):
        rows = self.rows()
        rows.append({'close_time_ms': 101 * 900000, 'is_closed': True, 'close': '1'})
        self.assertEqual(calculate_rsi(rows, 90000000, '15m')['rsi'], 100)
        rows[10]['close'] = 'NaN'
        self.assertEqual(calculate_rsi(rows, 90000000, '15m')['status'], 'invalid_data')
