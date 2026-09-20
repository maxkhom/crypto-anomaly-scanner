import asyncio
import copy
import unittest
from unittest.mock import Mock, patch

from bitunix import iso_time, MarketDataError
from score_service import compose_score, get_score

END = 1800000000000
NOW = END + 1000


def fixtures():
    def candles(interval, step, count):
        return {'symbol': 'BTCUSDT', 'exchange': 'bitunix', 'interval': interval,
                'as_of': iso_time(NOW), 'data_quality': 'ok', 'items': [
                    {'close_time_ms': END - index * step, 'is_closed': True,
                     'high': '101', 'low': '99', 'close': '100', 'volume_quote': '100'}
                    for index in range(count)]}
    sources = {
        'minute': candles('1m', 60000, 107), 'fifteen': candles('15m', 900000, 102),
        'oi': {'symbol': 'BTCUSDT', 'exchange': 'bybit', 'status': 'ok', 'unit': 'BTC',
               'measured_at': iso_time(END), 'score_component': {
                   'status': 'ok', 'normalized_score': 40, 'reason': 'OI example', 'version': 'oi_change_rank_5m_v1'}},
        'funding': {'symbol': 'BTCUSDT', 'exchange': 'bitunix', 'status': 'ok', 'unit': 'percent',
                    'fetched_at': iso_time(NOW), 'next_funding_time': iso_time(NOW + 3600000),
                    'funding_rate_pct': '0.15', 'min_funding_rate_pct': '-0.3', 'max_funding_rate_pct': '0.3'},
    }
    snapshot = {'symbol': 'BTCUSDT', 'exchange': 'bitunix', 'as_of': iso_time(NOW), 'status': 'live',
                'short_momentum': {'price_acceleration': {
                    'status': 'ok', 'score': 80, 'reason': 'Acceleration example',
                    'evaluated_to': iso_time(END), 'version': 'acceleration_rank_10s_v1',
                    'valid_samples': 180, 'required_samples': 180}}}
    return sources, snapshot


class CompositionTests(unittest.TestCase):
    def test_complete_score_breakdown_and_sources(self):
        sources, snapshot = fixtures()
        before = copy.deepcopy((sources, snapshot))
        result = compose_score('BTCUSDT', NOW, sources, snapshot)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['score'], 32.5)
        self.assertEqual(result['coverage_pct'], 100)
        self.assertEqual(result['score'], sum(row['points'] for row in result['components'].values()))
        self.assertEqual(result['components']['open_interest']['details']['exchange'], 'bybit')
        self.assertEqual(result['components']['extras']['details']['parts']['funding']['points'], 2.5)
        self.assertEqual((sources, snapshot), before)

    def test_binance_source_composes_without_changing_weights(self):
        sources, snapshot = fixtures()
        sources['oi']['exchange'] = 'binance'
        result = compose_score('BTCUSDT', NOW, sources, snapshot)
        self.assertEqual(result['score'], 32.5)
        self.assertEqual(result['markets'], ['bitunix', 'binance'])
        self.assertEqual(result['components']['open_interest']['details']['exchange'], 'binance')
        sources['oi']['exchange'] = 'unknown'
        self.assertIsNone(compose_score('BTCUSDT', NOW, sources, snapshot)['score'])

    def test_partial_oi_failure_does_not_erase_other_components(self):
        sources, snapshot = fixtures()
        sources['oi'] = {'status': 'unavailable', 'reason': 'Bybit: HTTP 403'}
        result = compose_score('BTCUSDT', NOW, sources, snapshot)
        self.assertIsNone(result['score'])
        self.assertEqual(result['coverage_pct'], 75)
        self.assertEqual(result['missing_components'], ['open_interest'])
        self.assertEqual(result['components']['price_acceleration']['points'], 20)
        self.assertIn('403', result['components']['open_interest']['reason'])

    def test_missing_stream_or_acceleration_gaps_do_not_become_zero(self):
        for snapshot in ({'status': 'unavailable', 'reason': 'No stream'}, fixtures()[1]):
            if 'short_momentum' in snapshot:
                snapshot['short_momentum']['price_acceleration'].update(status='insufficient_data', score=None)
            result = compose_score('BTCUSDT', NOW, fixtures()[0], snapshot)
            self.assertIsNone(result['score'])
            self.assertEqual(result['coverage_pct'], 75)
            self.assertIsNone(result['components']['price_acceleration']['points'])

    def test_wrong_symbol_and_future_time_rejected(self):
        for mutation in ('symbol', 'time'):
            sources, snapshot = fixtures()
            if mutation == 'symbol':
                sources['oi']['symbol'] = 'ETHUSDT'
            else:
                sources['oi']['measured_at'] = iso_time(NOW + 1)
            result = compose_score('BTCUSDT', NOW, sources, snapshot)
            self.assertIsNone(result['score'])
            self.assertIn(result['components']['open_interest']['status'], ('invalid_data', 'stale'))

    def test_oi_ages_during_request_and_funding_settlement_passes(self):
        sources, snapshot = fixtures()
        sources['oi']['measured_at'] = iso_time(NOW - 600001)
        sources['funding']['next_funding_time'] = iso_time(NOW)
        result = compose_score('BTCUSDT', NOW, sources, snapshot)
        self.assertEqual(result['components']['open_interest']['status'], 'stale')
        self.assertIsNone(result['components']['extras']['points'])
        self.assertEqual(result['components']['extras']['details']['parts']['funding']['status'], 'stale')

    def test_candle_boundary_crossing_never_reuses_older_current_window(self):
        sources, snapshot = fixtures()
        result = compose_score('BTCUSDT', END + 60000, sources, snapshot)
        self.assertIsNone(result['components']['relative_volume']['points'])
        self.assertEqual(result['components']['relative_volume']['status'], 'insufficient_data')

    def test_shared_candle_failure_blocks_volatility_and_extras(self):
        sources, snapshot = fixtures()
        sources['fifteen'] = {'status': 'unavailable', 'reason': 'Candle API offline'}
        result = compose_score('BTCUSDT', NOW, sources, snapshot)
        self.assertEqual(set(result['missing_components']), {'volatility', 'extras'})
        self.assertEqual(result['components']['extras']['details']['parts']['funding']['points'], 2.5)

    def test_stale_funding_and_candle_sources_block_contributions(self):
        for key, field, component in [('funding', 'fetched_at', 'extras'), ('minute', 'as_of', 'relative_volume'),
                                      ('fifteen', 'as_of', 'volatility')]:
            sources, snapshot = fixtures()
            sources[key][field] = iso_time(NOW - 60001)
            result = compose_score('BTCUSDT', NOW, sources, snapshot)
            self.assertEqual(result['components'][component]['status'], 'stale')
            self.assertIsNone(result['score'])


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_fifteen_minute_fetch_and_source_failure_isolation(self):
        sources, snapshot = fixtures()
        stream = Mock(states={'BTCUSDT': object()})
        stream.snapshot.return_value = snapshot
        def candles(symbol, interval, limit, closed):
            return sources['minute' if interval == '1m' else 'fifteen']
        with patch('score_service.market_data.get_candles', side_effect=candles) as request, \
             patch('score_service.get_open_interest', side_effect=MarketDataError('Bybit: HTTP 403')), \
             patch('score_service.get_funding', return_value=sources['funding']), \
             patch('score_service.time.time_ns', return_value=NOW * 1000000), \
             patch('score_service.SOURCE_LIMIT', asyncio.Semaphore(4)), \
             self.assertLogs('score_service', level='WARNING'):
            result = await get_score('BTCUSDT', stream)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result['missing_components'], ['open_interest'])
        stream.snapshot.assert_called_once_with('BTCUSDT')

    async def test_endpoint_returns_json_serializable_result(self):
        import json
        from main import anomaly_score
        sources, snapshot = fixtures()
        expected = compose_score('BTCUSDT', NOW, sources, snapshot)
        with patch('main.get_score', return_value=expected) as request:
            response = await anomaly_score('BTCUSDT')
        self.assertEqual(json.loads(json.dumps(response))['score'], 32.5)
        request.assert_awaited_once()
