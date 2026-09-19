import unittest
from open_interest import calculate_open_interest, STEP

END = 1789837500000


def payload():
    return {'retCode': 0, 'time': END + 1000, 'result': {'symbol': 'BTCUSDT', 'category': 'linear',
        'list': [{'timestamp': str(END - n * STEP), 'openInterest': '110' if n == 0 else '100'} for n in range(13)]}}


class OITests(unittest.TestCase):
    def test_all_periods_and_units(self):
        result = calculate_open_interest(payload())
        self.assertEqual(result['unit'], 'BTC')
        self.assertTrue(all(row['percent'] == 10 for row in result['changes'].values()))

    def test_gap_does_not_shorten_period(self):
        data = payload()
        data['result']['list'].pop(2)
        result = calculate_open_interest(data)
        self.assertEqual(result['changes']['5m']['status'], 'ok')
        self.assertIsNone(result['changes']['15m']['percent'])

    def test_stale_and_zero_baseline(self):
        data = payload()
        data['time'] = END + STEP * 2 + 1
        self.assertEqual(calculate_open_interest(data)['changes']['5m']['status'], 'stale')
        data = payload()
        data['result']['list'][1]['openInterest'] = '0'
        self.assertEqual(calculate_open_interest(data)['changes']['5m']['status'], 'zero_baseline')

    def test_invalid_or_conflicting_data(self):
        for value in ['NaN', '-1', 'Infinity']:
            data = payload()
            data['result']['list'][0]['openInterest'] = value
            with self.assertRaises(ValueError):
                calculate_open_interest(data)
        data = payload()
        data['result']['list'].append({'timestamp': str(END), 'openInterest': '200'})
        with self.assertRaises(ValueError):
            calculate_open_interest(data)
