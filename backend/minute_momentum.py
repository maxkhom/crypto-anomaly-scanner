"""Three chronological one-minute returns and their latest difference."""
from decimal import Decimal, InvalidOperation
from bitunix import iso_time

MINUTE_MS = 60_000


def calculate_minute_momentum(candles: list[dict], as_of_ms: int) -> dict:
    end = as_of_ms // MINUTE_MS * MINUTE_MS
    closed = {row['close_time_ms']: row for row in candles if row['is_closed'] and row['close_time_ms'] <= end}
    minutes = []
    raw_returns = []
    for offset in (2, 1, 0):
        finish = end - offset * MINUTE_MS
        start = finish - MINUTE_MS
        missing = sum(timestamp not in closed for timestamp in (start, finish))
        value = None
        status = 'insufficient_data' if missing else 'ok'
        warnings = 0
        if not missing:
            try:
                previous = Decimal(str(closed[start]['close']))
                current = Decimal(str(closed[finish]['close']))
                if not all(price.is_finite() and price > 0 for price in (previous, current)):
                    raise ValueError('Invalid price')
                value = (current / previous - 1) * 100
                warnings = sum(bool(closed[timestamp].get('warnings')) for timestamp in (start, finish))
            except (InvalidOperation, ValueError, TypeError, KeyError):
                status = 'invalid_price'
        raw_returns.append(value)
        minutes.append({'from_time': iso_time(start), 'to_time': iso_time(finish),
                        'percent': float(round(value, 4)) if value is not None else None,
                        'status': status, 'missing_count': missing, 'warning_count': warnings})
    previous, latest = raw_returns[-2:]
    available = previous is not None and latest is not None
    delta = latest - previous if available else None
    return {'minutes': minutes,
            'change_pp': float(round(delta, 4)) if delta is not None else None,
            'status': 'ok' if available else 'invalid_price' if any(row['status'] == 'invalid_price' for row in minutes[-2:]) else 'insufficient_data',
            'unit': 'percentage_points',
            'warning_count': sum(bool(closed[timestamp].get('warnings')) for timestamp in (end-2*MINUTE_MS, end-MINUTE_MS, end) if timestamp in closed)}
