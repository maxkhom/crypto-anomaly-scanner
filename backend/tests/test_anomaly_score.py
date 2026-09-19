import unittest
from decimal import Decimal

from anomaly_score import COMPONENTS, calculate_anomaly_score


def inputs(value=100):
    return {key: {'status': 'ok', 'score': value} for key, _, _ in COMPONENTS}


class AnomalyScoreTests(unittest.TestCase):
    def test_weights_and_endpoints(self):
        self.assertEqual(sum(weight for _, _, weight in COMPONENTS), 100)
        for value in (0, 50, 100):
            result = calculate_anomaly_score(inputs(value))
            self.assertEqual(result['score'], value)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['coverage_pct'], 100)

    def test_explainable_contributions_sum_to_score(self):
        data = inputs()
        for key, value in zip(data, (88, 96, 100, Decimal('93.333333333'), 60)):
            data[key].update(score=value, reason='Проверочный пример')
        result = calculate_anomaly_score(data)
        self.assertEqual(result['score'], 91)
        self.assertEqual([row['points'] for row in result['components'].values()], [22, 24, 25, 14, 6])
        self.assertEqual(sum(row['points'] for row in result['components'].values()), result['score'])
        self.assertEqual(result['components']['extras']['reason'], 'Проверочный пример')

    def test_missing_oi_does_not_become_zero_or_rescale(self):
        data = inputs()
        del data['open_interest']
        result = calculate_anomaly_score(data)
        self.assertIsNone(result['score'])
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['coverage_pct'], 75)
        self.assertEqual(result['missing_components'], ['open_interest'])
        self.assertIsNone(result['components']['open_interest']['points'])
        self.assertEqual(result['components']['relative_volume']['points'], 25)

    def test_stale_value_is_not_used(self):
        for status in ('stale', 'warming_up', 'insufficient_data', 'unavailable'):
            data = inputs()
            data['volatility']['status'] = status
            result = calculate_anomaly_score(data)
            self.assertIsNone(result['score'])
            self.assertIsNone(result['components']['volatility']['points'])
            self.assertEqual(result['coverage_pct'], 85)

    def test_invalid_values_cannot_produce_score(self):
        for value in (True, None, '50', -1, 101, float('nan'), float('inf'), Decimal('-Infinity')):
            with self.subTest(value=value):
                data = inputs()
                data['extras']['score'] = value
                result = calculate_anomaly_score(data)
                self.assertEqual(result['status'], 'invalid_data')
                self.assertIsNone(result['score'])

    def test_malformed_and_empty_inputs(self):
        self.assertEqual(calculate_anomaly_score({})['status'], 'unavailable')
        for value in ([], {'status': []}, {'status': 'unexpected'}):
            self.assertEqual(calculate_anomaly_score({'extras': value})['status'], 'invalid_data')
        with self.assertRaises(ValueError):
            calculate_anomaly_score({'typo': {'status': 'ok', 'score': 100}})
        with self.assertRaises(ValueError):
            calculate_anomaly_score([])

    def test_increasing_one_component_cannot_reduce_total(self):
        for key, _, _ in COMPONENTS:
            data = inputs(20)
            before = calculate_anomaly_score(data)['score']
            data[key]['score'] = 80
            self.assertGreater(calculate_anomaly_score(data)['score'], before)


if __name__ == '__main__':
    unittest.main()
