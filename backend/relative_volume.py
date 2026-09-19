"""Quote volume relative to twenty preceding windows of the same length."""

from decimal import Decimal, InvalidOperation

from bitunix import iso_time
from anomaly_score import calculate_anomaly_score

MINUTE_MS = 60_000
WINDOW_MINUTES = 5
BASELINE_WINDOWS = 20
REQUIRED_MINUTES = WINDOW_MINUTES * (BASELINE_WINDOWS + 1)


def _with_volume_score(result, baseline_volumes=None):
    """A descriptive upper-volume rank, not the magnitude of the RVOL ratio."""
    if result['period'] != '5m':
        return result
    reasons = {
        'missing_candles': 'Недостаточно завершённых свечей для сравнения объёма.',
        'invalid_volume': 'Некорректные данные объёма.',
        'zero_baseline': 'Исторический объём равен нулю; оценка недоступна.',
    }
    score = None
    exceeded = None
    reason = reasons.get(result['reason'], 'Оценка объёма недоступна.')
    if result['status'] == 'ok':
        current = Decimal(result['current_volume_usdt'])
        exceeded = sum(value < current for value in baseline_volumes)
        score = 100 * exceeded / BASELINE_WINDOWS
        reason = f'Объём последних 5 минут выше {exceeded} из 20 предыдущих пятиминутных объёмов. Равные объёмы не считаются превышенными.'
    component = calculate_anomaly_score({'relative_volume': {
        'status': result['status'], 'score': score, 'reason': reason,
    }})['components']['relative_volume']
    result['score_component'] = {
        **component, 'version': 'volume_rank_5m_v1',
        'exceeded_windows': exceeded, 'required_windows': BASELINE_WINDOWS,
        'evaluated_from': result['current_from'], 'evaluated_to': result['current_to'],
        'baseline_from': result['baseline_from'], 'baseline_to': result['baseline_to'],
    }
    return result


def calculate_relative_volume(candles: list[dict], as_of_ms: int, window_minutes: int = 5, candle_minutes: int = 1) -> dict:
    if (window_minutes, candle_minutes) not in ((5, 1), (15, 1), (60, 5)):
        raise ValueError('Supported RVOL windows/candles: 5/1, 15/1, 60/5 minutes')
    step_ms = candle_minutes * MINUTE_MS
    window_candles = window_minutes // candle_minutes
    required_minutes = window_minutes * (BASELINE_WINDOWS + 1)
    end = as_of_ms // step_ms * step_ms
    current_start = end - window_minutes * MINUTE_MS
    history_start = end - required_minutes * MINUTE_MS
    closed = {
        row['close_time_ms']: row for row in candles
        if row['is_closed'] and history_start < row['close_time_ms'] <= end
    }
    times = list(range(history_start + step_ms, end + 1, step_ms))
    missing = [timestamp for timestamp in times if timestamp not in closed]
    result = {
        'period': '1h' if window_minutes == 60 else f'{window_minutes}m',
        'candle_interval': f'{candle_minutes}m', 'rvol': None, 'status': 'insufficient_data',
        'reason': 'missing_candles' if missing else None,
        'current_volume_usdt': None, 'baseline_average_volume_usdt': None,
        'baseline_windows': BASELINE_WINDOWS,
        'current_from': iso_time(current_start), 'current_to': iso_time(end),
        'baseline_from': iso_time(history_start), 'baseline_to': iso_time(current_start),
        'missing_count': len(missing),
        'warning_count': sum(bool(row.get('warnings')) for row in closed.values()),
    }
    if missing:
        return _with_volume_score(result)
    try:
        volumes = [Decimal(str(closed[timestamp]['volume_quote'])) for timestamp in times]
        if any(not value.is_finite() or value < 0 for value in volumes):
            raise ValueError('Invalid volume')
    except (InvalidOperation, ValueError, KeyError, TypeError):
        result.update(status='invalid_data', reason='invalid_volume')
        return _with_volume_score(result)
    # The current window is excluded from the baseline.
    current = sum(volumes[-window_candles:], Decimal(0))
    baseline_volumes = [sum(volumes[start:start + window_candles], Decimal(0))
                        for start in range(0, len(volumes) - window_candles, window_candles)]
    baseline = sum(baseline_volumes, Decimal(0)) / BASELINE_WINDOWS
    result.update(current_volume_usdt=str(current), baseline_average_volume_usdt=str(baseline))
    if baseline == 0:
        result['reason'] = 'zero_baseline'
        return _with_volume_score(result)
    result.update(rvol=float(round(current / baseline, 4)), status='ok', reason=None)
    return _with_volume_score(result, baseline_volumes)
