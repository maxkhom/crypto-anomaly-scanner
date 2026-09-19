"""Bitunix funding values are percentage units, verified against its UI."""
import json
import time
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import urlopen

from bitunix import BASE_URL, MarketDataError, iso_time


def normalize_funding(payload, symbol, now_ms):
    if not isinstance(payload, dict) or payload.get('code') != 0:
        raise ValueError('Bitunix funding request failed')
    row = payload['data']
    if isinstance(row, list):
        if len(row) != 1:
            raise ValueError('Expected one funding record')
        row = row[0]
    if not isinstance(row, dict) or row.get('symbol') != symbol:
        raise ValueError('Unexpected funding symbol')
    rate, lower, upper = [Decimal(str(row[key])) for key in ('fundingRate', 'minFundingRate', 'maxFundingRate')]
    if not all(value.is_finite() for value in (rate, lower, upper)) or not lower <= rate <= upper:
        raise ValueError('Invalid funding rate or limits')
    interval = Decimal(str(row['fundingInterval']))
    stamp = Decimal(str(row['nextFundingTime']))
    if not interval.is_finite() or interval <= 0 or interval != interval.to_integral_value():
        raise ValueError('Invalid funding interval')
    if not stamp.is_finite() or stamp <= 0 or stamp != stamp.to_integral_value():
        raise ValueError('Invalid settlement timestamp')
    next_ms = int(stamp)
    return {'exchange': 'bitunix', 'symbol': symbol, 'funding_rate_pct': str(rate),
            'unit': 'percent', 'interval_hours': int(interval), 'next_funding_time': iso_time(next_ms),
            'min_funding_rate_pct': str(lower), 'max_funding_rate_pct': str(upper),
            'payment_direction': 'shorts_pay_longs' if rate < 0 else 'longs_pay_shorts' if rate > 0 else 'none',
            'status': 'ok' if next_ms > now_ms else 'settlement_time_passed',
            'fetched_at': iso_time(now_ms)}


def get_funding(symbol):
    url = BASE_URL + '/funding_rate?' + urlencode({'symbol': symbol})
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.load(response)
        return normalize_funding(payload, symbol, time.time_ns() // 1_000_000)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise MarketDataError('Не удалось получить корректную ставку финансирования Bitunix') from exc
