import unittest
from decimal import Decimal

from short_momentum import ShortMomentum, MAX_BOUNDARIES, iso


class ShortMomentumTests(unittest.TestCase):
    def test_three_windows_and_tempo(self):
        data = ShortMomentum()
        for second in range(41):
            data.add(second - 0.1, str(100 + second))
        result = data.calculate(40, True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([x["percent"] for x in result["windows"]], [9.0909, 8.3333, 7.6923])
        self.assertEqual(result["change_pp"], -0.641)

    def test_warmup_and_disconnected(self):
        data = ShortMomentum()
        data.add(0, "100")
        self.assertEqual(data.calculate(20, True)["status"], "warming_up")
        self.assertIsNone(data.calculate(40, False)["change_pp"])

    def test_boundary_gap_is_not_zero_return(self):
        data = ShortMomentum()
        for second in range(41):
            if second not in (18, 19, 20):
                data.add(second - 0.1, "100")
        result = data.calculate(40, True)
        self.assertEqual(result["status"], "missing_data")
        self.assertIsNone(result["windows"][0]["percent"])

    def test_silence_preserves_history_and_marks_gaps(self):
        data = ShortMomentum()
        for second in range(101):
            data.add(second - 0.1, "100")
        data.calculate(100, True)
        saved = dict(data.boundaries)
        started = data.started
        data.add(130, "110")
        result = data.calculate(130, True)
        self.assertEqual(data.started, started)
        self.assertEqual(result["status"], "missing_data")
        self.assertTrue(all(dict(data.boundaries)[stamp] == price for stamp, price in saved.items()))
        self.assertGreater(result["history"]["valid_intervals"], 0)
        self.assertTrue(all(window["percent"] is None for window in result["windows"]))
        for second in range(131, 161):
            data.add(second - 0.1, "110")
        self.assertEqual(data.calculate(160, True)["windows"][-1]["status"], "ok")

    def test_long_silence_expires_old_data_without_new_warmup(self):
        data = ShortMomentum()
        data.add(0, "100")
        data.add(100000, "110")
        result = data.calculate(100000, True)
        self.assertEqual(data.started, 0)
        self.assertEqual(len(data.boundaries), MAX_BOUNDARIES)
        self.assertEqual(result["history"]["status"], "missing_data")
        self.assertEqual(result["history"]["valid_intervals"], 0)
        self.assertIsNone(result["history"]["percentile"])

    def test_future_sample_not_used_for_boundary(self):
        data = ShortMomentum()
        for second in range(40):
            data.add(second - 0.1, "100")
        data.add(40.5, "200")
        self.assertEqual(data.calculate(41, True)["windows"][-1]["percent"], 0)


class HistoryTests(unittest.TestCase):
    def build(self, final="110", missing=False):
        data = ShortMomentum()
        for second in range(1811):
            if missing and second in (898, 899, 900):
                continue
            data.add(second - 0.1, final if second == 1810 else "100")
        return data

    def test_current_is_excluded_and_zero_baseline_is_valid(self):
        result = self.build().calculate(1810, True)["history"]
        self.assertEqual(result["valid_intervals"], 180)
        self.assertEqual(result["percentile"], 100)
        self.assertEqual(result["baseline_to"], result["evaluated_from"])

    def test_equal_moves_do_not_count_as_exceeded(self):
        self.assertEqual(self.build("100").calculate(1810, True)["history"]["percentile"], 0)

    def test_missing_boundary_blocks_score(self):
        result = self.build(missing=True).calculate(1810, True)["history"]
        self.assertEqual(result["status"], "missing_data")
        self.assertEqual(result["missing_intervals"], 2)
        self.assertIsNone(result["percentile"])

    def test_downward_move_uses_absolute_size(self):
        self.assertEqual(self.build("90").calculate(1810, True)["history"]["percentile"], 100)

    def test_closed_result_does_not_change_with_future_trade(self):
        data = self.build()
        before = data.calculate(1810, True)
        data.add(1810.5, "200")
        after = data.calculate(1811, True)
        self.assertEqual(before["history"], after["history"])
        self.assertEqual(before["windows"][-1]["percent"], after["windows"][-1]["percent"])
        self.assertLessEqual(len(data.boundaries), MAX_BOUNDARIES)

    def test_common_boundaries_despite_different_start_times(self):
        first, second = ShortMomentum(), ShortMomentum()
        for tick in range(51):
            first.add(tick + 0.1, "100")
            if tick > 3:
                second.add(tick + 0.5, "100")
        self.assertEqual(first.calculate(51, True)["windows"][-1]["to_time"],
                         second.calculate(51, True)["windows"][-1]["to_time"])


class LatestValidHistoryTests(unittest.TestCase):
    def build(self, gaps=(), final='110'):
        data = ShortMomentum()
        data.started = -1
        data.next_boundary = 3010
        data.boundaries.extend((stamp, None if stamp in gaps else Decimal(final if stamp == 3000 else '100'))
                               for stamp in range(290, 3001, 10))
        return data

    def test_small_gap_uses_older_real_returns(self):
        data = self.build(gaps=(1500,))
        before = list(data.boundaries)
        result = data.calculate(3005, True)
        history = result['history']
        self.assertEqual(history['status'], 'ok')
        self.assertEqual(history['valid_intervals'], 180)
        self.assertEqual(history['skipped_intervals'], 2)
        self.assertEqual(history['baseline_from'], iso(1170))
        self.assertEqual(history['baseline_to'], iso(2990))
        self.assertEqual(history['baseline_span_seconds'], 1820)
        self.assertEqual(history['percentile'], 100)
        self.assertEqual(list(data.boundaries), before)
        self.assertEqual(result['price_acceleration']['status'], 'insufficient_data')
        self.assertIsNone(result['anomaly_score']['components']['price_acceleration']['points'])
        self.assertIsNone(result['anomaly_score']['score'])

    def test_current_missing_never_falls_back(self):
        for stamp in (2990, 3000):
            result = self.build(gaps=(stamp,)).calculate(3005, True)['history']
            self.assertEqual(result['valid_intervals'], 180)
            self.assertIsNone(result['percentile'])
            self.assertEqual(result['reason'], 'missing_current_return')
            self.assertEqual(result['evaluated_to'], iso(3000))

    def test_latest_180_selected_and_ties_unchanged(self):
        data = self.build(final='100')
        # Older huge movements must not enter the newest 180-return baseline.
        data.boundaries[1] = (300, Decimal('1000'))
        result = data.calculate(3005, True)['history']
        self.assertEqual(result['baseline_from'], iso(1190))
        self.assertEqual(result['valid_intervals'], 180)
        self.assertEqual(result['skipped_intervals'], 0)
        self.assertEqual(result['percentile'], 0)

    def test_strict_percentile_and_absolute_direction_with_gaps(self):
        for final in ('110', '90'):
            data = self.build(gaps=(1500,), final=final)
            # Two historical returns have magnitude greater than 10%.
            data.boundaries[151] = (1800, Decimal('200'))
            history = data.calculate(3005, True)['history']
            self.assertEqual(history['percentile'], round(178 / 180 * 100, 2))

    def test_lookback_boundary_inclusive_but_older_return_excluded(self):
        data = self.build()
        data.boundaries.clear()
        # 179 eligible historical returns plus one outside the search window.
        data.boundaries.extend((stamp, Decimal('100')) for stamp in range(280, 2081, 10))
        data.boundaries.extend([(2990, Decimal('100')), (3000, Decimal('110'))])
        history = data.calculate(3005, True)['history']
        self.assertEqual(history['search_from'], iso(290))
        self.assertEqual(history['search_to'], iso(2990))
        self.assertEqual(history['max_lookback_seconds'], 2700)
        self.assertEqual(history['valid_intervals'], 179)
        self.assertEqual(history['missing_intervals'], 1)
        self.assertIsNone(history['percentile'])
        data.boundaries.append((2090, Decimal('100')))
        ready = data.calculate(3005, True)['history']
        self.assertEqual(ready['valid_intervals'], 180)
        self.assertEqual(ready['baseline_from'], iso(290))
        self.assertEqual(ready['baseline_age_seconds'], 2700)
        self.assertEqual(ready['percentile'], 100)

    def test_no_bridging_over_missing_boundary(self):
        data = self.build()
        data.boundaries.clear()
        # Separated real points cannot form even one ten-second return.
        data.boundaries.extend((stamp, Decimal('100')) for stamp in range(290, 2990, 20))
        data.boundaries.extend([(2990, Decimal('100')), (3000, Decimal('110'))])
        history = data.calculate(3005, True)['history']
        self.assertEqual(history['valid_intervals'], 0)
        self.assertIsNone(history['percentile'])

    def test_disconnect_and_future_trade_do_not_change_closed_selection(self):
        data = self.build(gaps=(1500,))
        before = data.calculate(3005, True)
        self.assertIsNone(data.calculate(3005, False)['history']['percentile'])
        data.add(3006, '999')
        after = data.calculate(3007, True)
        self.assertEqual(before['history'], after['history'])
        self.assertEqual(before['price_acceleration'], after['price_acceleration'])

    def test_old_history_does_not_affect_acceleration_or_score(self):
        data = self.build()
        before = data.calculate(3005, True)
        for index in range(80):
            stamp, _ = data.boundaries[index]
            data.boundaries[index] = (stamp, None)
        after = data.calculate(3005, True)
        self.assertEqual(before['price_acceleration'], after['price_acceleration'])
        self.assertEqual(before['anomaly_score'], after['anomaly_score'])
