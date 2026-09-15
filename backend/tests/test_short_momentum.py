import unittest

from short_momentum import ShortMomentum


class ShortMomentumTests(unittest.TestCase):
    def test_three_windows_and_tempo(self):
        data = ShortMomentum()
        for second in range(41):
            data.add(second, str(100 + second))
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
                data.add(second, "100")
        result = data.calculate(40, True)
        self.assertEqual(result["status"], "missing_data")
        self.assertIsNone(result["windows"][0]["percent"])

    def test_silence_restarts_warmup(self):
        data = ShortMomentum()
        data.add(0, "100")
        data.add(50, "110")
        self.assertEqual(data.calculate(50, True)["status"], "warming_up")

    def test_future_sample_not_used_for_boundary(self):
        data = ShortMomentum()
        for second in range(40):
            data.add(second, "100")
        data.add(40.5, "200")
        self.assertEqual(data.calculate(41, True)["windows"][-1]["percent"], 0)
