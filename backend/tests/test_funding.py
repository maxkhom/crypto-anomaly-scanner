import unittest
from funding import normalize_funding


def payload(**changes):
    return {'code': 0, 'data': {'symbol': 'BTCUSDT', 'fundingRate': '-0.008389',
            'fundingInterval': 8, 'nextFundingTime': '1789862400000',
            'maxFundingRate': '0.3', 'minFundingRate': '-0.3', **changes}}


class FundingTests(unittest.TestCase):
    def test_percentage_units_match_observed_ui(self):
        result = normalize_funding(payload(), 'BTCUSDT', 1789838787331)
        self.assertEqual(result['funding_rate_pct'], '-0.008389')
        self.assertEqual(result['payment_direction'], 'shorts_pay_longs')
        self.assertEqual(result['interval_hours'], 8)
        self.assertEqual(result['status'], 'ok')

    def test_documented_list_and_payment_signs(self):
        for rate, direction in [('0', 'none'), ('0.01', 'longs_pay_shorts')]:
            data = payload(fundingRate=rate)
            data['data'] = [data['data']]
            self.assertEqual(normalize_funding(data, 'BTCUSDT', 1789838787331)['payment_direction'], direction)

    def test_invalid_values_and_wrong_symbol(self):
        for changes in ({'fundingRate': 'NaN'}, {'fundingRate': '0.4'}, {'fundingInterval': 0},
                        {'fundingInterval': 1.5}, {'nextFundingTime': 'Infinity'}, {'symbol': 'ETHUSDT'}):
            with self.assertRaises(ValueError):
                normalize_funding(payload(**changes), 'BTCUSDT', 1789838787331)

    def test_passed_settlement_is_flagged(self):
        self.assertEqual(normalize_funding(payload(), 'BTCUSDT', 1789862400000)['status'], 'settlement_time_passed')
