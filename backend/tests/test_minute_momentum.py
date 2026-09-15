import unittest
from minute_momentum import calculate_minute_momentum

END = 1789483200000


def rows(prices):
    return [{'close_time_ms': END - (3-i)*60000, 'close': str(price), 'is_closed': True, 'warnings': []} for i,price in enumerate(prices)]


class MinuteMomentumTests(unittest.TestCase):
    def test_growth_and_chronological_order(self):
        result = calculate_minute_momentum(rows([100, 101, 103.02, 106.1106]), END+1000)
        self.assertEqual([x['percent'] for x in result['minutes']], [1,2,3])
        self.assertEqual(result['change_pp'], 1)

    def test_accelerating_fall(self):
        result = calculate_minute_momentum(rows([100,99,97.02,94.1094]), END)
        self.assertEqual([x['percent'] for x in result['minutes']], [-1,-2,-3])
        self.assertEqual(result['change_pp'], -1)

    def test_slowing_fall_has_positive_difference(self):
        result = calculate_minute_momentum(rows([100,98,96.04,95.0796]), END)
        self.assertEqual(result['change_pp'], 1)
        self.assertEqual(result['minutes'][-1]['percent'], -1)

    def test_missing_oldest_only_affects_first_return(self):
        result = calculate_minute_momentum(rows([100,101,102,103])[1:], END)
        self.assertIsNone(result['minutes'][0]['percent'])
        self.assertEqual(result['status'],'ok')

    def test_gap_blocks_difference(self):
        data=rows([100,101,102,103]);data.pop(2)
        result=calculate_minute_momentum(data, END)
        self.assertIsNone(result['change_pp'])
        self.assertEqual(result['status'],'insufficient_data')

    def test_open_or_stale_latest_is_not_used(self):
        data=rows([100,101,102,103]);data[-1]['is_closed']=False
        self.assertIsNone(calculate_minute_momentum(data,END)['change_pp'])
        self.assertIsNone(calculate_minute_momentum(rows([100,101,102,103]),END+60000)['change_pp'])

    def test_invalid_price(self):
        for value in [0,-1,'NaN','Infinity','bad']:
            result=calculate_minute_momentum(rows([100,101,value,103]), END)
            self.assertEqual(result['status'],'invalid_price')
            self.assertIsNone(result['change_pp'])

    def test_no_movement_and_warning(self):
        data=rows([100,100,100,100]);data[-1]['warnings']=['open_outside_range_matches_previous_close']
        result=calculate_minute_momentum(data,END)
        self.assertEqual(result['change_pp'],0)
        self.assertEqual(result['warning_count'],1)

    def test_difference_before_rounding(self):
        data=rows([100,100,100.000049,100.00009800002401])
        result=calculate_minute_momentum(data,END)
        self.assertEqual(result['change_pp'],0)
