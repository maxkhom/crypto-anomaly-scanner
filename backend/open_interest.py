"""Bybit BTCUSDT OI snapshots; values use Bybit's two-sided definition."""
import json
from decimal import Decimal
from urllib.request import urlopen

from bitunix import MarketDataError, iso_time

STEP = 300_000


def calculate_open_interest(payload):
    if payload['retCode'] != 0:
        raise ValueError('Bybit rejected the request')
    source = payload['result']
    if source['symbol'] != 'BTCUSDT' or source['category'] != 'linear':
        raise ValueError('Unexpected Bybit contract')
    now = int(payload['time'])
    if now <= 0:
        raise ValueError('Invalid server time')
    points = {}
    for row in source['list']:
        timestamp = int(row['timestamp'])
        value = Decimal(row['openInterest'])
        if timestamp <= 0 or timestamp % STEP or timestamp > now or not value.is_finite() or value < 0:
            raise ValueError('Invalid OI snapshot')
        if timestamp in points and points[timestamp] != value:
            raise ValueError('Conflicting OI snapshots')
        points[timestamp] = value
    if not points:
        raise ValueError('Bybit returned no OI snapshots')
    latest = max(points)
    stale = now - latest > 2 * STEP
    current = points[latest]
    changes = {}
    for label, steps in [('5m', 1), ('15m', 3), ('1h', 12)]:
        start = latest - steps * STEP
        missing = sum(t not in points for t in range(start, latest + 1, STEP))
        status = 'stale' if stale else 'insufficient_data' if missing else 'zero_baseline' if points[start] == 0 else 'ok'
        changes[label] = {'percent': float(round((current / points[start] - 1) * 100, 4)) if status == 'ok' else None,
                          'status': status, 'missing_count': missing,
                          'from_time': iso_time(start), 'to_time': iso_time(latest)}
    return {'exchange': 'bybit', 'symbol': 'BTCUSDT', 'category': 'linear', 'unit': 'BTC',
            'definition': 'sum_of_both_sides', 'source_field': 'openInterest',
            'open_interest': str(current), 'status': 'stale' if stale else 'ok',
            'measured_at': iso_time(latest), 'source_server_time': iso_time(now),
            'age_seconds': round((now - latest) / 1000, 3), 'interval': '5min', 'changes': changes}


def get_open_interest():
    url = 'https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=5min&limit=13'
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.load(response)
        return calculate_open_interest(payload)
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise MarketDataError('Не удалось получить корректную историю OI Bybit') from exc
