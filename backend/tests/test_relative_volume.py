import unittest
from relative_volume import calculate_relative_volume

END = 1789483200000


def history(current='500', baseline='100'):
    return [
        {'close_time_ms':END-i*60000, 'is_closed':True,
         'volume_quote':current if i < 5 else baseline, 'warnings':[]}
        for i in range(105)
    ]


class RelativeVolumeTests(unittest.TestCase):
    def test_five_times_and_exclusion_of_current_window(self):
        result = calculate_relative_volume(history(), END+30000)
        self.assertEqual(result['rvol'], 5)
        self.assertEqual(result['current_volume_usdt'], '2500')
        self.assertEqual(result['baseline_average_volume_usdt'], '500')
        self.assertEqual(result['status'], 'ok')

    def test_normal_and_zero_current(self):
        self.assertEqual(calculate_relative_volume(history('100'), END)['rvol'], 1)
        self.assertEqual(calculate_relative_volume(history('0'), END)['rvol'], 0)

    def test_zero_baseline_is_unavailable(self):
        result=calculate_relative_volume(history(baseline='0'), END)
        self.assertIsNone(result['rvol'])
        self.assertEqual(result['reason'],'zero_baseline')

    def test_missing_current_or_baseline_candle(self):
        for index in [0, 3, 5, 50, 104]:
            rows=history()
            rows.pop(index)
            with self.subTest(index=index):
                result=calculate_relative_volume(rows, END)
                self.assertIsNone(result['rvol'])
                self.assertEqual(result['missing_count'],1)

    def test_unclosed_candle_does_not_count(self):
        rows=history()
        rows[0]['is_closed']=False
        self.assertEqual(calculate_relative_volume(rows, END)['missing_count'],1)

    def test_extra_old_and_future_candles_are_excluded(self):
        rows=history()+[
            {'close_time_ms': END-105*60000,'is_closed':True,'volume_quote':'999999'},
            {'close_time_ms': END+60000,'is_closed':True,'volume_quote':'999999'},
        ]
        self.assertEqual(calculate_relative_volume(rows, END)['rvol'],5)

    def test_invalid_volume_is_rejected(self):
        for value in ['-1','NaN','Infinity','bad']:
            rows=history()
            rows[5]['volume_quote']=value
            self.assertEqual(calculate_relative_volume(rows,END)['status'],'invalid_data')

    def test_warning_is_preserved(self):
        rows=history()
        rows[8]['warnings']=['open_outside_range_matches_previous_close']
        result=calculate_relative_volume(rows,END)
        self.assertEqual(result['warning_count'],1)
        self.assertEqual(result['rvol'],5)

    def test_empty_history(self):
        result=calculate_relative_volume([],END)
        self.assertEqual(result['missing_count'],105)
        self.assertIsNone(result['rvol'])


if __name__ == '__main__':
    unittest.main()


class FifteenMinuteVolumeTests(unittest.TestCase):
    def rows(self):
        return [{'close_time_ms': END - i * 60000, 'is_closed': True,
                 'volume_quote': '300' if i < 15 else '100'} for i in range(315)]

    def test_baseline_excludes_current_fifteen_minutes(self):
        result = calculate_relative_volume(self.rows(), END + 30000, 15)
        self.assertEqual(result['period'], '15m')
        self.assertEqual(result['rvol'], 3)
        self.assertEqual(result['current_volume_usdt'], '4500')
        self.assertEqual(result['baseline_average_volume_usdt'], '1500')
        self.assertEqual(result['baseline_windows'], 20)

    def test_each_side_of_window_boundary_is_required(self):
        for index in (0, 14, 15, 314):
            rows = self.rows()
            rows.pop(index)
            result = calculate_relative_volume(rows, END, 15)
            self.assertEqual(result['missing_count'], 1)
            self.assertIsNone(result['rvol'])

    def test_unclosed_and_out_of_range_are_not_used(self):
        rows = self.rows()
        rows[0]['is_closed'] = False
        rows.append({'close_time_ms': END + 60000, 'is_closed': True, 'volume_quote': '999999'})
        result = calculate_relative_volume(rows, END, 15)
        self.assertIsNone(result['rvol'])
        self.assertEqual(result['missing_count'], 1)

    def test_zero_baseline_and_invalid_volume(self):
        rows = self.rows()
        for row in rows[15:]:
            row['volume_quote'] = '0'
        self.assertEqual(calculate_relative_volume(rows, END, 15)['reason'], 'zero_baseline')
        rows[15]['volume_quote'] = 'NaN'
        self.assertEqual(calculate_relative_volume(rows, END, 15)['status'], 'invalid_data')

    def test_unsupported_period_rejected(self):
        with self.assertRaises(ValueError):
            calculate_relative_volume([], END, 10)
