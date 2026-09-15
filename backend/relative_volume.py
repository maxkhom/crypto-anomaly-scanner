"""Five-minute quote volume relative to twenty preceding five-minute windows."""

from decimal import Decimal, InvalidOperation

from bitunix import iso_time

MINUTE_MS = 60_000
WINDOW_MINUTES = 5
BASELINE_WINDOWS = 20
REQUIRED_MINUTES = WINDOW_MINUTES * (BASELINE_WINDOWS + 1)


def calculate_relative_volume(candles: list[dict], as_of_ms: int) -> dict:
    end = as_of_ms // MINUTE_MS * MINUTE_MS
    current_start = end - WINDOW_MINUTES * MINUTE_MS
    history_start = end - REQUIRED_MINUTES * MINUTE_MS
    closed = {
        row['close_time_ms']: row for row in candles
        if row['is_closed'] and history_start < row['close_time_ms'] <= end
    }
    times = list(range(history_start + MINUTE_MS, end + 1, MINUTE_MS))
    missing = [timestamp for timestamp in times if timestamp not in closed]
    result = {
        'period': '5m', 'rvol': None, 'status': 'insufficient_data',
        'reason': 'missing_candles' if missing else None,
        'current_volume_usdt': None, 'baseline_average_volume_usdt': None,
        'baseline_windows': BASELINE_WINDOWS,
        'current_from': iso_time(current_start), 'current_to': iso_time(end),
        'baseline_from': iso_time(history_start), 'baseline_to': iso_time(current_start),
        'missing_count': len(missing),
        'warning_count': sum(bool(row.get('warnings')) for row in closed.values()),
    }
    if missing:
        return result
    try:
        volumes = [Decimal(str(closed[timestamp]['volume_quote'])) for timestamp in times]
        if any(not value.is_finite() or value < 0 for value in volumes):
            raise ValueError('Invalid volume')
    except (InvalidOperation, ValueError, KeyError, TypeError):
        result.update(status='invalid_data', reason='invalid_volume')
        return result
    # The final five minutes are excluded from the baseline.
    current = sum(volumes[-WINDOW_MINUTES:], Decimal(0))
    baseline = sum(volumes[:-WINDOW_MINUTES], Decimal(0)) / BASELINE_WINDOWS
    result.update(current_volume_usdt=str(current), baseline_average_volume_usdt=str(baseline))
    if baseline == 0:
        result['reason'] = 'zero_baseline'
        return result
    result.update(rvol=float(round(current / baseline, 4)), status='ok', reason=None)
    return result
