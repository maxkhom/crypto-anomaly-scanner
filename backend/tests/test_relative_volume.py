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
    def test_volume_score_counts_windows_not_individual_candles(self):
        rows = history(current='20')
        # Twenty windows of five minutes, with mean minute volumes 1..20.
        for index, row in enumerate(rows[5:]):
            row['volume_quote'] = str(index // 5 + 1)
        result = calculate_relative_volume(rows, END)
        component = result['score_component']
        self.assertEqual(component['exceeded_windows'], 19)
        self.assertEqual(component['normalized_score'], 95)
        self.assertEqual(component['points'], 23.75)
        self.assertEqual(component['max_points'], 25)
        self.assertEqual(component['baseline_to'], component['evaluated_from'])
        self.assertEqual(result['rvol'], round(20 / 10.5, 4))

    def test_volume_score_ties_zero_and_record(self):
        for current, points in [('100', 0), ('0', 0), ('500', 25)]:
            with self.subTest(current=current):
                component = calculate_relative_volume(history(current), END)['score_component']
                self.assertEqual(component['points'], points)
                self.assertEqual(component['status'], 'ok')

    def test_volume_score_missing_invalid_and_zero_baseline(self):
        missing = history()[1:]
        invalid = history()
        invalid[8]['volume_quote'] = 'NaN'
        for rows, status in [(missing, 'insufficient_data'), (invalid, 'invalid_data'),
                             (history(baseline='0'), 'insufficient_data')]:
            with self.subTest(status=status):
                component = calculate_relative_volume(rows, END)['score_component']
                self.assertIsNone(component['points'])
                self.assertIsNone(component['normalized_score'])
                self.assertIsNone(component['exceeded_windows'])
                self.assertEqual(component['status'], status)

    def test_volume_score_ignores_future_and_is_stable_inside_minute(self):
        rows = history()
        before = calculate_relative_volume(rows, END)['score_component']
        rows.append({'close_time_ms': END + 60000, 'is_closed': False, 'volume_quote': '99999999'})
        self.assertEqual(before, calculate_relative_volume(rows, END + 59999)['score_component'])

    def test_volume_score_uses_unrounded_values(self):
        # Both RVOL values round to 1, but the strict rank keeps the difference.
        low = calculate_relative_volume(history('99.99999'), END)
        high = calculate_relative_volume(history('100.00001'), END)
        self.assertEqual(low['rvol'], high['rvol'])
        self.assertEqual(low['score_component']['points'], 0)
        self.assertEqual(high['score_component']['points'], 25)

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
        self.assertNotIn('score_component', result)

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


class HourVolumeTests(unittest.TestCase):
    def rows(self):
        end = END // 300000 * 300000
        return [{'close_time_ms': end - i * 300000, 'is_closed': True,
                 'volume_quote': '200' if i < 12 else '100'} for i in range(252)]

    def test_hour_ratio_excludes_current_twelve_candles(self):
        result = calculate_relative_volume(self.rows(), END, 60, 5)
        self.assertEqual(result['period'], '1h')
        self.assertEqual(result['candle_interval'], '5m')
        self.assertEqual(result['rvol'], 2)
        self.assertEqual(result['current_volume_usdt'], '2400')
        self.assertEqual(result['baseline_average_volume_usdt'], '1200')
        self.assertNotIn('score_component', result)

    def test_missing_boundary_or_oldest_candle(self):
        for index in (0, 11, 12, 251):
            rows = self.rows()
            rows.pop(index)
            result = calculate_relative_volume(rows, END, 60, 5)
            self.assertIsNone(result['rvol'])
            self.assertEqual(result['missing_count'], 1)

    def test_end_is_aligned_to_five_minutes(self):
        end = END // 300000 * 300000
        self.assertEqual(calculate_relative_volume(self.rows(), end, 60, 5),
                         calculate_relative_volume(self.rows(), end + 299999, 60, 5))
        self.assertEqual(calculate_relative_volume(self.rows(), end + 300000, 60, 5)['missing_count'], 1)

    def test_zero_baseline_and_unclosed_candle(self):
        rows = self.rows()
        rows[0]['is_closed'] = False
        self.assertEqual(calculate_relative_volume(rows, END, 60, 5)['missing_count'], 1)
        rows = self.rows()
        for row in rows[12:]:
            row['volume_quote'] = '0'
        self.assertEqual(calculate_relative_volume(rows, END, 60, 5)['reason'], 'zero_baseline')
