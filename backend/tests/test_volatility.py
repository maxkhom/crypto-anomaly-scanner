import unittest
from decimal import Decimal
from volatility import calculate_volatility, INTERVALS


class VolatilityTests(unittest.TestCase):
    def test_score_ties_and_current_spike(self):
        rows = self.rows()
        result = calculate_volatility(rows, 90000000, '15m')
        self.assertEqual(result['score_component']['points'], 0)
        rows[-1].update(high='110', low='90')
        score = calculate_volatility(rows, 90000000, '15m')['score_component']
        self.assertEqual(score['normalized_score'], 100)
        self.assertEqual(score['points'], 15)
        self.assertEqual(score['exceeded_samples'], 20)
        self.assertLess(score['baseline_last_at'], score['evaluated_at'])

    def test_score_ranks_percentages_not_absolute_atr(self):
        rows = self.rows()
        for row in rows:
            row['close'] = '99'
        rows[-1].update(high='100.01', low='98', close='100')
        result = calculate_volatility(rows, 90000000, '15m')
        self.assertGreater(Decimal(result['atr']), 2)
        self.assertLess(result['atr_pct'], float(Decimal(2) / 99 * 100))
        self.assertEqual(result['score_component']['points'], 0)

    def test_score_weight_and_strict_ties(self):
        from volatility import _with_volatility_score
        result = _with_volatility_score({'interval': '15m', 'status': 'ok'}, 90000000,
                                        [Decimal(value) for value in [*range(1, 21), 20]])
        self.assertEqual(result['score_component']['exceeded_samples'], 19)
        self.assertEqual(result['score_component']['points'], 14.25)

    def test_missing_invalid_and_duplicate_conflict_block_score(self):
        missing = self.rows()[1:]
        invalid = self.rows()
        invalid[2]['close'] = 'NaN'
        conflict = self.rows()
        conflict.append({**conflict[-1], 'high': '120'})
        for rows in (missing, invalid, conflict):
            self.assertIsNone(calculate_volatility(rows, 90000000, '15m')['score_component']['points'])

    def test_future_candle_cannot_change_score_and_hour_has_no_contribution(self):
        rows = self.rows()
        before = calculate_volatility(rows, 90000000, '15m')['score_component']
        rows.append({**rows[-1], 'close_time_ms': 90900000, 'high': '99999'})
        self.assertEqual(before, calculate_volatility(rows, 90000000, '15m')['score_component'])
        self.assertNotIn('score_component', calculate_volatility(self.rows('1h'), 360000000, '1h'))

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
