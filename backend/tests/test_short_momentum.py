import unittest

from short_momentum import ShortMomentum


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
        self.assertEqual(len(data.boundaries), 182)
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
        self.assertLessEqual(len(data.boundaries), 182)

    def test_common_boundaries_despite_different_start_times(self):
        first, second = ShortMomentum(), ShortMomentum()
        for tick in range(51):
            first.add(tick + 0.1, "100")
            if tick > 3:
                second.add(tick + 0.5, "100")
        self.assertEqual(first.calculate(51, True)["windows"][-1]["to_time"],
                         second.calculate(51, True)["windows"][-1]["to_time"])
