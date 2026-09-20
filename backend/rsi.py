"""RSI(14), Wilder smoothing, seeded on a fixed 100-close history."""
from decimal import Decimal, InvalidOperation
from bitunix import iso_time
from extras_score import score_rsi

PERIOD = 14
HISTORY_CLOSES = 100
INTERVALS = {'15m': 900000, '1h': 3600000}


def _with_score(result):
    return {**result, 'score_part': score_rsi(result)} if result['interval'] == '15m' else result


def wilder_rsi(closes, period=PERIOD):
    if len(closes) < period + 1:
        raise ValueError('Insufficient closes')
    changes = [right - left for left, right in zip(closes, closes[1:])]
    gains = [max(value, Decimal(0)) for value in changes]
    losses = [max(-value, Decimal(0)) for value in changes]
    gain = sum(gains[:period], Decimal(0)) / period
    loss = sum(losses[:period], Decimal(0)) / period
    for up, down in zip(gains[period:], losses[period:]):
        gain = (gain * (period - 1) + up) / period
        loss = (loss * (period - 1) + down) / period
    if gain == 0 and loss == 0:
        return Decimal(50)  # Explicit convention for a completely flat history.
    if loss == 0:
        return Decimal(100)
    return 100 - 100 / (1 + gain / loss)


def calculate_rsi(candles, as_of_ms, interval):
    step = INTERVALS[interval]
    end = as_of_ms // step * step
    times = list(range(end - (HISTORY_CLOSES - 1) * step, end + 1, step))
    rows = {}
    conflict = False
    for row in candles:
        stamp = row['close_time_ms']
        if row['is_closed'] and times[0] <= stamp <= end and stamp % step == 0:
            if stamp in rows and rows[stamp]['close'] != row['close']:
                conflict = True
            rows[stamp] = row
    missing = sum(stamp not in rows for stamp in times)
    result = {'period': PERIOD, 'interval': interval, 'method': 'wilder', 'rsi': None,
              'status': 'insufficient_data', 'history_closes': HISTORY_CLOSES,
              'missing_count': missing, 'warning_count': sum(bool(row.get('warnings')) for row in rows.values()),
              'from_time': iso_time(times[0]), 'to_time': iso_time(end),
              'flat_history_value': 50}
    if conflict:
        return _with_score({**result, 'status': 'invalid_data'})
    if missing:
        return _with_score(result)
    try:
        closes = [Decimal(str(rows[stamp]['close'])) for stamp in times]
        if any(not value.is_finite() or value <= 0 for value in closes):
            raise ValueError('Invalid close')
        value = wilder_rsi(closes)
    except (InvalidOperation, ValueError, TypeError, KeyError):
        return _with_score({**result, 'status': 'invalid_data'})
    return _with_score({**result, 'status': 'ok', 'rsi': float(round(value, 4))})
