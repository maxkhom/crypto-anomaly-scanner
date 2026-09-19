"""ATR(14) with Wilder smoothing over 99 true ranges from 100 candles."""
from decimal import Decimal, InvalidOperation
from bitunix import iso_time

INTERVALS = {'15m': 900000, '1h': 3600000}


def calculate_volatility(candles, as_of_ms, interval):
    step = INTERVALS[interval]
    end = as_of_ms // step * step
    times = list(range(end - 99 * step, end + 1, step))
    rows = {}
    conflict = False
    for row in candles:
        stamp = row['close_time_ms']
        if row['is_closed'] and times[0] <= stamp <= end and stamp % step == 0:
            if stamp in rows and any(rows[stamp].get(key) != row.get(key) for key in ('high', 'low', 'close')):
                conflict = True
            rows[stamp] = row
    missing = sum(stamp not in rows for stamp in times)
    result = {'period': 14, 'interval': interval, 'method': 'wilder', 'atr': None, 'atr_pct': None,
              'reference_price': None, 'range_14': None, 'range_14_pct': None,
              'status': 'insufficient_data', 'history_candles': 100,
              'missing_count': missing, 'warning_count': sum(bool(row.get('warnings')) for row in rows.values()),
              'from_time': iso_time(times[0]), 'to_time': iso_time(end),
              'range_from': iso_time(end - 14 * step), 'range_to': iso_time(end), 'unit': 'USDT'}
    if conflict:
        return {**result, 'status': 'invalid_data'}
    if missing:
        return result
    try:
        values = [tuple(Decimal(str(rows[stamp][key])) for key in ('high', 'low', 'close')) for stamp in times]
        if any(not all(value.is_finite() and value > 0 for value in row) or not row[1] <= row[2] <= row[0] for row in values):
            raise ValueError('Invalid candle range')
        ranges = [max(high - low, abs(high - previous[2]), abs(low - previous[2]))
                  for previous, (high, low, close) in zip(values, values[1:])]
        atr = sum(ranges[:14], Decimal(0)) / 14
        for value in ranges[14:]:
            atr = (atr * 13 + value) / 14
        price = values[-1][2]
        span = max(row[0] for row in values[-14:]) - min(row[1] for row in values[-14:])
        return {**result, 'status': 'ok', 'atr': str(atr), 'atr_pct': float(round(atr / price * 100, 6)),
                'reference_price': str(price), 'range_14': str(span), 'range_14_pct': float(round(span / price * 100, 6))}
    except (InvalidOperation, ValueError, KeyError, TypeError):
        return {**result, 'status': 'invalid_data'}
