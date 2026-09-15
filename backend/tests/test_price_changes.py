import unittest
from price_changes import calculate_price_changes, MINUTE_MS

END = 1789483200000


def candle(minutes_ago, price='100', **extra):
    return {'close_time_ms': END - minutes_ago * MINUTE_MS, 'close': price, 'is_closed': True, 'warnings': [], **extra}


class PriceChangeTests(unittest.TestCase):
    def test_known_returns_and_exact_hour_boundary(self):
        rows = [candle(i) for i in range(241)]
        rows[0]['close'] = '105'
        result = calculate_price_changes(rows, END + 30_000)
        for metric in result['changes'].values():
            self.assertEqual(metric['percent'], 5)
            self.assertEqual(metric['status'], 'ok')
        self.assertEqual(result['reference_price'], '105')

    def test_negative_and_zero_returns(self):
        for price, expected in [('90', -10), ('100', 0)]:
            result = calculate_price_changes([candle(1), candle(0, price)], END)
            self.assertEqual(result['changes']['1m']['percent'], expected)

    def test_internal_gap_blocks_only_affected_periods(self):
        rows = [candle(i) for i in range(61) if i != 10]
        result = calculate_price_changes(rows, END)['changes']
        self.assertEqual(result['5m']['percent'], 0)
        self.assertIsNone(result['15m']['percent'])
        self.assertEqual(result['15m']['missing_count'], 1)
        self.assertIsNone(result['1h']['percent'])

    def test_sixty_candles_are_not_enough_for_one_hour(self):
        result = calculate_price_changes([candle(i) for i in range(60)], END)
        self.assertIsNone(result['changes']['1h']['percent'])
        self.assertEqual(result['changes']['1h']['missing_count'], 1)

    def test_stale_history_does_not_move_reference_back(self):
        result = calculate_price_changes([candle(i) for i in range(1, 62)], END)
        self.assertIsNone(result['reference_price'])
        self.assertTrue(all(metric['percent'] is None for metric in result['changes'].values()))

    def test_open_and_future_candles_are_excluded(self):
        rows = [candle(1), candle(0, '200', is_closed=False), candle(-1, '300')]
        result = calculate_price_changes(rows, END)
        self.assertIsNone(result['reference_price'])

    def test_empty_history_is_missing_not_zero(self):
        result = calculate_price_changes([], END)
        self.assertEqual(result['changes']['1m']['missing_count'], 2)
        self.assertIsNone(result['changes']['1m']['percent'])

    def test_open_warning_does_not_change_close_return(self):
        rows = [candle(1, warnings=['open_outside_range_matches_previous_close']), candle(0, '105')]
        result = calculate_price_changes(rows, END)['changes']['1m']
        self.assertEqual(result['percent'], 5)
        self.assertEqual(result['warning_count'], 1)

    def test_invalid_price_is_not_a_return(self):
        for value in ['0', '-1', 'NaN', 'Infinity']:
            result = calculate_price_changes([candle(1, value), candle(0)], END)
            self.assertEqual(result['changes']['1m']['status'], 'invalid_price')

    def test_four_hours_need_241_closings(self):
        result = calculate_price_changes([candle(i) for i in range(240)], END)
        self.assertIsNone(result['changes']['4h']['percent'])
        self.assertEqual(result['changes']['4h']['missing_count'], 1)

    def test_gap_in_older_history_does_not_block_one_hour(self):
        result = calculate_price_changes([candle(i) for i in range(241) if i != 150], END)
        self.assertEqual(result['changes']['1h']['percent'], 0)
        self.assertIsNone(result['changes']['4h']['percent'])


if __name__ == '__main__':
    unittest.main()
