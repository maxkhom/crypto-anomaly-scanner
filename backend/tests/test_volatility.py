import unittest
from decimal import Decimal
from volatility import calculate_volatility, INTERVALS


class VolatilityTests(unittest.TestCase):
    def rows(self, interval='15m'):
        return [{'close_time_ms': (i + 1) * INTERVALS[interval], 'is_closed': True,
                 'high': '101', 'low': '99', 'close': '100'} for i in range(100)]

    def test_constant_ranges_and_percent(self):
        for interval, step in INTERVALS.items():
            result = calculate_volatility(self.rows(interval), step * 100, interval)
            self.assertEqual(Decimal(result['atr']), 2)
            self.assertEqual(result['atr_pct'], 2)
            self.assertEqual(result['range_14_pct'], 2)

    def test_gap_and_wilder_update(self):
        rows = self.rows()
        rows[-1].update(high='111', low='109', close='110')
        result = calculate_volatility(rows, 90000000, '15m')
        self.assertEqual(Decimal(result['atr']), Decimal(37) / 14)
        self.assertEqual(Decimal(result['range_14']), 12)

    def test_missing_or_unclosed_blocks_result(self):
        rows = self.rows()
        rows[20]['is_closed'] = False
        result = calculate_volatility(rows, 90000000, '15m')
        self.assertEqual(result['missing_count'], 1)
        self.assertIsNone(result['atr'])

    def test_future_excluded_and_invalid_rejected(self):
        rows = self.rows()
        rows.append({**rows[-1], 'close_time_ms': 90900000, 'high': '99999'})
        self.assertEqual(calculate_volatility(rows, 90000000, '15m')['atr_pct'], 2)
        rows[5]['low'] = 'NaN'
        self.assertEqual(calculate_volatility(rows, 90000000, '15m')['status'], 'invalid_data')
