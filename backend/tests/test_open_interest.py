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


class SymbolTests(unittest.TestCase):
    def test_eth_uses_eth_units(self):
        data = payload()
        data['result']['symbol'] = 'ETHUSDT'
        result = calculate_open_interest(data, 'ETHUSDT')
        self.assertEqual(result['symbol'], 'ETHUSDT')
        self.assertEqual(result['unit'], 'ETH')
        self.assertEqual(result['changes']['1h']['percent'], 10)

    def test_wrong_contract_and_unsupported_symbol_rejected(self):
        with self.assertRaises(ValueError):
            calculate_open_interest(payload(), 'ETHUSDT')
        with self.assertRaises(ValueError):
            calculate_open_interest(payload(), 'SOLUSDT')


class ContractMatchTests(unittest.TestCase):
    def metadata(self, **changes):
        return {'result': {'category': 'linear', 'list': [{
            'symbol': 'SOLUSDT', 'baseCoin': 'SOL', 'quoteCoin': 'USDT',
            'settleCoin': 'USDT', 'contractType': 'LinearPerpetual',
            'status': 'Trading', 'isPreListing': False, **changes}]}}

    def test_sol_and_rejection_cases(self):
        from open_interest import match_contract
        self.assertEqual(match_contract(self.metadata(), 'SOLUSDT', 'SOL'), 'SOL')
        for changes in ({'baseCoin': 'OTHER'}, {'quoteCoin': 'USDC'}, {'settleCoin': 'USDC'},
                        {'contractType': 'LinearFutures'}, {'status': 'Settled'}, {'isPreListing': True}):
            self.assertIsNone(match_contract(self.metadata(**changes), 'SOLUSDT', 'SOL'))
        self.assertIsNone(match_contract({'result': {'category': 'linear', 'list': []}}, 'SOLUSDT', 'SOL'))

    def test_verified_sol_calculation(self):
        data = payload()
        data['result']['symbol'] = 'SOLUSDT'
        result = calculate_open_interest(data, 'SOLUSDT', 'SOL')
        self.assertEqual(result['unit'], 'SOL')
        self.assertEqual(result['changes']['5m']['percent'], 10)

    def test_missing_contract_skips_oi_request(self):
        from unittest.mock import patch
        from open_interest import get_open_interest
        with patch('open_interest.market_data.get_active_usdt_futures', return_value=[{'symbol': 'SOLUSDT', 'base': 'SOL'}]), patch('open_interest.bybit_request', return_value={'result': {'category': 'linear', 'list': []}}) as request:
            self.assertEqual(get_open_interest('SOLUSDT')['status'], 'unavailable')
            self.assertEqual(request.call_count, 1)
