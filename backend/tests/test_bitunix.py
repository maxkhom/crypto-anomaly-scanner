"""Deterministic service checks; no network requests or credentials required."""

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from bitunix import BitunixMarketDataService, InstrumentNotFound, MarketDataError, normalize_candles
from market import get_market

# Real Bitunix response supplied during integration, newest candle first.
CANDLES = [
    {"open":"76445","high":"76480.7","low":"76389","close":"76389","quoteVol":"31.5403","baseVol":"2410748.64904","time":"1789482120000"},
    {"open":"76398.5","high":"76449.4","low":"76363.1","close":"76445","quoteVol":"36.5251","baseVol":"2790967.76978","time":"1789482060000"},
    {"open":"76360.7","high":"76398.5","low":"76334.5","close":"76398.5","quoteVol":"14.9323","baseVol":"1140222.65719","time":"1789482000000"},
    {"open":"76308.8","high":"76378.9","low":"76308.7","close":"76360.7","quoteVol":"30.3283","baseVol":"2315254.99912","time":"1789481940000"},
    {"open":"76323.3","high":"76323.3","low":"76289.8","close":"76308.8","quoteVol":"31.3986","baseVol":"2395881.20359","time":"1789481880000"},
]
AS_OF = 1789482150000
PAIR = {"symbol": "BTCUSDT", "base": "BTC", "quote": "USDT", "symbolStatus": "OPEN"}


class CandleTests(unittest.TestCase):
    def test_order_units_and_closure(self):
        result = normalize_candles(CANDLES, '1m', AS_OF)
        self.assertEqual([row['open_time_ms'] for row in result], sorted(int(row['time']) for row in CANDLES))
        self.assertEqual(result[-1]['volume_base'], '31.5403')
        self.assertEqual(result[-1]['volume_quote'], '2410748.64904')
        self.assertEqual([row['is_closed'] for row in result], [True, True, True, True, False])

    def test_closure_boundary(self):
        row = normalize_candles(CANDLES[:1], '1m', 1789482180000)[0]
        self.assertTrue(row['is_closed'])

    def test_invalid_values_are_rejected(self):
        for changes in ({'open':'NaN'}, {'close':'999999'}, {'quoteVol':'-1'}, {'time':'1789482120001'}, {'time':True}, {'baseVol':'Infinity'}):
            with self.subTest(changes=changes), self.assertRaises(MarketDataError):
                normalize_candles([{**CANDLES[0], **changes}], '1m', AS_OF)

    def test_swapped_volume_units_are_rejected(self):
        row = {**CANDLES[0], 'quoteVol': CANDLES[0]['baseVol'], 'baseVol': CANDLES[0]['quoteVol']}
        with self.assertRaises(MarketDataError):
            normalize_candles([row], '1m', AS_OF)

    def test_duplicate_policy(self):
        self.assertEqual(len(normalize_candles([CANDLES[0], CANDLES[0]], '1m', AS_OF)), 1)
        with self.assertRaises(MarketDataError):
            normalize_candles([CANDLES[0], {**CANDLES[0], 'close':'76400'}], '1m', AS_OF)

    def test_zero_volume(self):
        row = {**CANDLES[0], 'quoteVol':'0', 'baseVol':'0'}
        self.assertEqual(normalize_candles([row], '1m', AS_OF)[0]['volume_base'], '0')


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = BitunixMarketDataService()

    def test_instrument_filter(self):
        rows = [PAIR, {**PAIR, 'symbol':'STOPUSDT', 'symbolStatus':'STOP'}, {**PAIR, 'symbol':'BTCUSDC','quote':'USDC'}]
        with patch.object(self.service, 'fetch_rows', return_value=rows):
            self.assertEqual(self.service.get_active_usdt_futures(), [{'symbol':'BTCUSDT','base':'BTC','quote':'USDT','status':'OPEN'}])

    def test_closed_only_and_query(self):
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], CANDLES]) as fetch, patch('bitunix.time.time_ns', return_value=AS_OF * 1_000_000):
            result = self.service.get_candles('BTCUSDT','1m',5,True)
            self.assertEqual(result['count'],4)
            self.assertEqual(result['received_count'],5)
            self.assertEqual(result['gaps'],[])
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(fetch.call_args.args[1]['type'], 'LAST_PRICE')

    def test_gaps_are_reported(self):
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], [CANDLES[0], CANDLES[2]]]), patch('bitunix.time.time_ns', return_value=AS_OF * 1_000_000):
            result = self.service.get_candles('BTCUSDT','1m',5,False)
            self.assertEqual(result['count'],2)
            self.assertEqual(result['gaps'][0]['missing_count'],1)

    def test_unknown_instrument(self):
        with patch.object(self.service, 'fetch_rows', return_value=[PAIR]) as fetch, self.assertRaises(InstrumentNotFound):
            self.service.get_candles('UNKNOWNUSDT','1m',5,True)
        self.assertEqual(fetch.call_count,1)

    def test_reported_bitunix_bad_ohlc_preserves_other_candles(self):
        bad = {"open":"76389", "high":"76383.1", "low":"76269.8", "close":"76345.5", "quoteVol":"35.6805", "baseVol":"2722986.42104", "time":"1789482180000"}
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], [bad, CANDLES[0]]]), patch('bitunix.time.time_ns', return_value=1789483215344 * 1_000_000):
            result = self.service.get_candles('BTCUSDT', '1m', 200, True)
        self.assertEqual(result['received_count'], 2)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['data_quality'], 'warning')
        self.assertEqual(result['rejected_count'], 0)
        self.assertEqual(result['warning_count'], 1)
        self.assertEqual(result['items'][1]['warnings'], ['open_outside_range_matches_previous_close'])
        self.assertEqual(result['items'][1]['high'], bad['high'])
        self.assertEqual(result['items'][1]['open'], bad['open'])
        self.assertEqual(result['items'][0]['open'], CANDLES[0]['open'])

    def test_outside_open_requires_adjacent_matching_close(self):
        bad = {**CANDLES[0], 'open':'80000'}
        for rows in ([bad], [CANDLES[1], bad], [CANDLES[2], {**bad, 'open':CANDLES[2]['close'], 'high':'76390'}]):
            with self.subTest(rows=rows), patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], rows]), patch('bitunix.time.time_ns', return_value=AS_OF * 1_000_000):
                result = self.service.get_candles('BTCUSDT', '1m', 5, False)
                self.assertEqual(result['rejected_count'], 1)

    def test_rejected_middle_candle_creates_gap(self):
        rows = [CANDLES[0], {**CANDLES[1], 'high':'1'}, CANDLES[2]]
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], rows]), patch('bitunix.time.time_ns', return_value=AS_OF * 1_000_000):
            result = self.service.get_candles('BTCUSDT', '1m', 5, False)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['gaps'][0]['missing_count'], 1)
        self.assertEqual(result['data_quality'], 'partial')

    def test_all_rejected_is_unavailable(self):
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], [{**CANDLES[0], 'open':'NaN'}]]), patch('bitunix.time.time_ns', return_value=AS_OF * 1_000_000):
            result = self.service.get_candles('BTCUSDT', '1m', 5, False)
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['rejected_count'], 1)
        self.assertEqual(result['data_quality'], 'unavailable')

    def test_empty_candles(self):
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], []]):
            self.assertEqual(self.service.get_candles('BTCUSDT','1m',5,True)['count'], 0)

    def test_two_history_pages_use_exclusive_boundary(self):
        rows = [{**CANDLES[0], 'open':'76400', 'time':str(AS_OF // 60000 * 60000 - i * 60000)} for i in range(243)]
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], rows[:200], rows[200:]]) as fetch, patch('bitunix.time.time_ns', return_value=AS_OF * 1_000_000):
            result = self.service.get_candles('BTCUSDT', '1m', 243, False)
        self.assertEqual(result['count'], 243)
        self.assertEqual(result['gaps'], [])
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(fetch.call_args.args[1]['endTime'], int(rows[199]['time']))
        self.assertEqual(fetch.call_args.args[1]['limit'], 43)

    def test_history_overlap_is_rejected(self):
        with patch.object(self.service, 'fetch_rows', side_effect=[[PAIR], CANDLES, CANDLES]), self.assertRaises(MarketDataError):
            self.service.get_candles('BTCUSDT', '1m', 243, True)

    def test_transport_errors(self):
        for error in (URLError('offline'), HTTPError('https://example.invalid',429,'rate limit',{},None)):
            with self.subTest(error=error), patch('bitunix.urlopen', side_effect=error), self.assertRaises(MarketDataError):
                self.service.fetch_rows('tickers')

    def test_bad_payloads(self):
        for payload in (b'not json', b'{"code":1,"data":[]}', b'{"code":0,"data":null}'):
            with self.subTest(payload=payload), patch('bitunix.urlopen', return_value=io.BytesIO(payload)), self.assertRaises(MarketDataError):
                self.service.fetch_rows('tickers')

    def test_transport_query_encoding(self):
        with patch('bitunix.urlopen', return_value=io.BytesIO(json.dumps({'code':0,'data':[]}).encode())) as request:
            self.service.fetch_rows('kline', {'symbol':'BTCUSDT','interval':'1m','limit':5})
            self.assertIn('symbol=BTCUSDT&interval=1m&limit=5',request.call_args.args[0])
            self.assertEqual(request.call_args.kwargs['timeout'],10)

    def test_existing_table_contract(self):
        tickers = [{'symbol':'BTCUSDT','lastPrice':'105','open':'100','quoteVol':'99999'}]
        with patch('market.market_data.fetch_rows', side_effect=[[PAIR],tickers]):
            result=get_market()
        self.assertEqual(result['count'],1)
        self.assertEqual(result['items'][0]['change_24h_pct'],5)
        self.assertEqual(result['items'][0]['volume_24h_usdt'],'99999')


if __name__ == '__main__':
    unittest.main()
