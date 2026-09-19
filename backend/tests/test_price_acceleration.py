import unittest
from decimal import Decimal
from price_acceleration import calculate_price_acceleration
from short_momentum import ShortMomentum


class AccelerationTests(unittest.TestCase):
    def test_strict_rank_and_current_excluded(self):
        # Historical differences: 1..180; evaluated difference: 172.
        values = [Decimal(0)]
        for difference in [*range(1, 181), 172]:
            values.append(values[-1] + difference)
        result = calculate_price_acceleration(values, True, False)
        self.assertEqual(result['score'], 95)
        self.assertEqual(result['valid_samples'], 180)
        self.assertEqual(result['change_pp'], 172)

    def test_constant_speed_and_constant_price_have_zero_acceleration(self):
        for value in (0, Decimal('0.01'), Decimal('-0.01')):
            self.assertEqual(calculate_price_acceleration([value] * 182, True, False)['score'], 0)

    def test_up_down_and_sudden_deceleration_are_symmetric(self):
        for values in ([0] * 181 + [1], [0] * 181 + [-1], [1] * 181 + [0]):
            self.assertEqual(calculate_price_acceleration(values, True, False)['score'], 100)

    def test_missing_history_and_missing_current_block_score(self):
        for index in (0, 90, 180, 181):
            values = [Decimal(0)] * 182
            values[index] = None
            result = calculate_price_acceleration(values, True, False)
            self.assertIsNone(result['score'])
            self.assertEqual(result['status'], 'insufficient_data')

    def test_warmup_disconnect_and_invalid_data(self):
        self.assertEqual(calculate_price_acceleration([None] * 182, True, True)['status'], 'warming_up')
        self.assertIsNone(calculate_price_acceleration([0] * 181 + [1], False, False)['score'])
        for value in (float('nan'), float('inf'), True, '0'):
            self.assertEqual(calculate_price_acceleration([0] * 181 + [value], True, False)['status'], 'invalid_data')

    def test_integration_score_and_future_trade(self):
        data = ShortMomentum()
        for second in range(1821):
            data.add(second - 0.1, '110' if second == 1820 else '100')
        before = data.calculate(1820, True)
        component = before['anomaly_score']['components']['price_acceleration']
        self.assertEqual(component['points'], 25)
        self.assertEqual(before['anomaly_score']['coverage_pct'], 25)
        self.assertIsNone(before['anomaly_score']['score'])
        self.assertEqual(before['price_acceleration']['baseline_to'], before['price_acceleration']['evaluated_from'])
        data.add(1820.5, '150')
        after = data.calculate(1821, True)
        self.assertEqual(before['price_acceleration'], after['price_acceleration'])
        self.assertIsNone(data.calculate(1821, False)['anomaly_score']['components']['price_acceleration']['points'])
