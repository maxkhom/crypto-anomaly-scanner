import unittest

from extras_score import score_funding, score_rsi, calculate_extras


def funding(rate='0.15', **changes):
    return {'status': 'ok', 'unit': 'percent', 'funding_rate_pct': rate,
            'min_funding_rate_pct': '-0.6', 'max_funding_rate_pct': '0.3', **changes}


def rsi(value=85, **changes):
    return {'status': 'ok', 'rsi': value, 'interval': '15m', 'period': 14, 'method': 'wilder', **changes}


class ExtrasTests(unittest.TestCase):
    def test_funding_percentage_units_and_asymmetric_limits(self):
        for rate, expected in [('0', 0), ('0.15', 2.5), ('-0.3', 2.5), ('0.3', 5), ('-0.6', 5)]:
            self.assertEqual(score_funding(funding(rate))['points'], expected)
        self.assertEqual(score_funding(funding('0', min_funding_rate_pct='0', max_funding_rate_pct='0'))['points'], 0)

    def test_rsi_boundaries_symmetry_and_neutral_zone(self):
        for value, expected in [(0, 5), (15, 2.5), (30, 0), (50, 0), (70, 0), (85, 2.5), (100, 5)]:
            with self.subTest(value=value):
                self.assertEqual(score_rsi(rsi(value))['points'], expected)

    def test_funding_expired_or_invalid_is_not_zero(self):
        self.assertEqual(score_funding(funding(status='settlement_time_passed'))['status'], 'stale')
        for data in (funding('NaN'), funding('Infinity'), funding(True), funding('0.31'),
                     funding(unit='fraction'), funding(min_funding_rate_pct='0.1')):
            self.assertEqual(score_funding(data)['status'], 'invalid_data')
            self.assertIsNone(score_funding(data)['points'])

    def test_rsi_missing_invalid_and_wrong_timeframe(self):
        for data in (rsi(-1), rsi(101), rsi(float('nan')), rsi(True), rsi(interval='1h'),
                     rsi(period=7), rsi(method='simple'), rsi(status='insufficient_data')):
            self.assertIsNone(score_rsi(data)['points'])

    def test_combination_requires_both_and_matches_displayed_parts(self):
        result = calculate_extras(funding(), rsi())
        self.assertEqual(result['points'], 5)
        self.assertEqual(result['normalized_score'], 50)
        self.assertEqual(result['max_points'], 10)
        self.assertEqual(calculate_extras(funding('0.3'), rsi(100))['points'], 10)
        self.assertEqual(calculate_extras(funding('0'), rsi(50))['points'], 0)
        for part in ({'status': 'unavailable'}, funding(status='settlement_time_passed')):
            incomplete = calculate_extras(part, rsi())
            self.assertIsNone(incomplete['points'])
            self.assertEqual(incomplete['parts']['rsi']['points'], 2.5)
        rounded = calculate_extras(funding('0.1'), rsi(80))
        self.assertEqual(rounded['points'], sum(part['points'] for part in rounded['parts'].values()))

    def test_funding_and_rsi_api_calculation_integration(self):
        from funding import normalize_funding
        from rsi import calculate_rsi
        payload = {'code': 0, 'data': {'symbol': 'BTCUSDT', 'fundingRate': '0.15',
                   'minFundingRate': '-0.3', 'maxFundingRate': '0.3', 'fundingInterval': 8,
                   'nextFundingTime': 1789862400000}}
        self.assertEqual(normalize_funding(payload, 'BTCUSDT', 1789838787331)['score_part']['points'], 2.5)
        self.assertIsNone(normalize_funding(payload, 'BTCUSDT', 1789862400000)['score_part']['points'])
        self.assertIsNone(calculate_rsi([], 90000000, '15m')['score_part']['points'])
        self.assertNotIn('score_part', calculate_rsi([], 90000000, '1h'))
