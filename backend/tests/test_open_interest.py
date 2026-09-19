import unittest
from open_interest import calculate_open_interest, STEP

END = 1789837500000


def payload():
    return {'retCode': 0, 'time': END + 1000, 'result': {'symbol': 'BTCUSDT', 'category': 'linear',
        'list': [{'timestamp': str(END - n * STEP), 'openInterest': '110' if n == 0 else '100'} for n in range(13)]}}


class OITests(unittest.TestCase):
    def test_source_http_error_survives_service_boundary(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from open_interest import get_open_interest
        from bitunix import MarketDataError
        with patch('open_interest.market_data.get_active_usdt_futures', return_value=[{'symbol': 'BTCUSDT', 'base': 'BTC'}]), patch('open_interest.urlopen', side_effect=HTTPError('https://api.bybit.com', 403, 'Forbidden', {}, None)), self.assertLogs('open_interest', level='WARNING'):
            with self.assertRaisesRegex(MarketDataError, 'HTTP 403.*instruments-info'):
                get_open_interest('BTCUSDT')

    def test_api_rejection_and_connection_error(self):
        from unittest.mock import patch
        from urllib.error import URLError
        from open_interest import bybit_request
        from bitunix import MarketDataError
        with patch('open_interest.urlopen'), patch('open_interest.json.load', return_value={'retCode': 10006}):
            with self.assertRaisesRegex(MarketDataError, 'retCode=10006'):
                bybit_request('open-interest')
        with patch('open_interest.urlopen', side_effect=URLError('connection failed')):
            with self.assertRaisesRegex(MarketDataError, 'ошибка соединения'):
                bybit_request('open-interest')

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


class OIScoreTests(unittest.TestCase):
    def data(self, final='110'):
        data = payload()
        data['result']['list'] = [{'timestamp': str(END - n * STEP),
                                  'openInterest': final if n == 0 else '100'} for n in range(22)]
        return data

    def test_growth_decline_ties_and_current_exclusion(self):
        for final, points in [('110', 25), ('90', 25), ('100', 0), ('0', 25)]:
            with self.subTest(final=final):
                result = calculate_open_interest(self.data(final))['score_component']
                self.assertEqual(result['points'], points)
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result['baseline_to'], result['evaluated_from'])

    def test_rank_and_weighted_points(self):
        data = self.data()
        # One historical 10% rise and its correction exceed the current 5% rise.
        data['result']['list'][10]['openInterest'] = '110'
        data['result']['list'][0]['openInterest'] = '105'
        score = calculate_open_interest(data)['score_component']
        self.assertEqual(score['exceeded_windows'], 18)
        self.assertEqual(score['normalized_score'], 90)
        self.assertEqual(score['points'], 22.5)

    def test_older_gap_blocks_score_but_keeps_short_changes(self):
        data = self.data()
        data['result']['list'].pop(20)
        result = calculate_open_interest(data)
        self.assertEqual(result['changes']['1h']['status'], 'ok')
        self.assertEqual(result['score_component']['missing_snapshots'], 1)
        self.assertIsNone(result['score_component']['points'])
        self.assertEqual(result['score_component']['status'], 'insufficient_data')

    def test_zero_denominator_and_stale_data_block_score(self):
        for index in (1, 10, 21):
            data = self.data()
            data['result']['list'][index]['openInterest'] = '0'
            self.assertIsNone(calculate_open_interest(data)['score_component']['points'])
        data = self.data()
        data['time'] = END + STEP * 2 + 1
        score = calculate_open_interest(data)['score_component']
        self.assertIsNone(score['points'])
        self.assertEqual(score['status'], 'stale')

    def test_short_history_and_input_order(self):
        self.assertIsNone(calculate_open_interest(payload())['score_component']['points'])
        data = self.data()
        before = calculate_open_interest(data)['score_component']
        data['result']['list'].reverse()
        data['result']['list'].append({'timestamp': str(END - 22 * STEP), 'openInterest': '999999'})
        self.assertEqual(before, calculate_open_interest(data)['score_component'])

    def test_service_fetches_enough_history_in_one_request(self):
        from unittest.mock import patch
        from open_interest import get_open_interest
        metadata = ContractMatchTests().metadata(symbol='BTCUSDT', baseCoin='BTC')
        with patch('open_interest.market_data.get_active_usdt_futures', return_value=[{'symbol': 'BTCUSDT', 'base': 'BTC'}]), patch('open_interest.bybit_request', side_effect=[metadata, self.data()]) as request:
            self.assertEqual(get_open_interest()['score_component']['points'], 25)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.kwargs['limit'], 22)


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
