"""ATR(14) with Wilder smoothing over 99 true ranges from 100 candles."""
from decimal import Decimal, InvalidOperation
from bitunix import iso_time
from anomaly_score import calculate_anomaly_score

INTERVALS = {'15m': 900000, '1h': 3600000}
SCORE_BASELINE = 20


def _with_volatility_score(result, end, atr_percentages=None):
    if result['interval'] != '15m':
        return result
    score, exceeded = None, None
    reason = ('Недостаточно завершённых свечей для оценки волатильности.'
              if result['status'] == 'insufficient_data' else 'Некорректные данные свечей.')
    if result['status'] == 'ok':
        current = atr_percentages[-1]
        baseline = atr_percentages[-SCORE_BASELINE - 1:-1]
        exceeded = sum(value < current for value in baseline)
        score = 100 * exceeded / SCORE_BASELINE
        reason = f'Текущий ATR% выше {exceeded} из 20 предыдущих значений ATR% на свечах 15 минут. Равные значения не считаются превышенными.'
    component = calculate_anomaly_score({'volatility': {
        'status': result['status'], 'score': score, 'reason': reason,
    }})['components']['volatility']
    step = INTERVALS['15m']
    return {**result, 'score_component': {
        **component, 'version': 'atr_pct_rank_15m_v1',
        'required_samples': SCORE_BASELINE, 'exceeded_samples': exceeded,
        'evaluated_at': iso_time(end), 'baseline_first_at': iso_time(end - SCORE_BASELINE * step),
        'baseline_last_at': iso_time(end - step),
    }}


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
        return _with_volatility_score({**result, 'status': 'invalid_data'}, end)
    if missing:
        return _with_volatility_score(result, end)
    try:
        values = [tuple(Decimal(str(rows[stamp][key])) for key in ('high', 'low', 'close')) for stamp in times]
        if any(not all(value.is_finite() and value > 0 for value in row) or not row[1] <= row[2] <= row[0] for row in values):
            raise ValueError('Invalid candle range')
        ranges = [max(high - low, abs(high - previous[2]), abs(low - previous[2]))
                  for previous, (high, low, close) in zip(values, values[1:])]
        atr = sum(ranges[:14], Decimal(0)) / 14
        atr_percentages = [atr / values[14][2] * 100]
        for index, value in enumerate(ranges[14:], start=15):
            atr = (atr * 13 + value) / 14
            # Normalize each historical ATR by its own contemporaneous close.
            atr_percentages.append(atr / values[index][2] * 100)
        price = values[-1][2]
        span = max(row[0] for row in values[-14:]) - min(row[1] for row in values[-14:])
        return _with_volatility_score({**result, 'status': 'ok', 'atr': str(atr), 'atr_pct': float(round(atr / price * 100, 6)),
                'reference_price': str(price), 'range_14': str(span), 'range_14_pct': float(round(span / price * 100, 6))}, end, atr_percentages)
    except (InvalidOperation, ValueError, KeyError, TypeError):
        return _with_volatility_score({**result, 'status': 'invalid_data'}, end)
