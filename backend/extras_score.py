"""Provisional rules: proximity to funding cap and RSI outside 30–70.

Each rule contributes at most five points. These are heuristic scales,
not historical ranks. Both inputs are required for the combined component.
"""
from decimal import Decimal, InvalidOperation
from anomaly_score import calculate_anomaly_score

VERSION = 'funding_cap_rsi_edges_v1'
RSI_LOWER = Decimal(30)
RSI_UPPER = Decimal(70)
PART_MAX = 5


def _part(status, reason, score=None):
    return {'version': VERSION, 'status': status, 'normalized_score': None if score is None else float(score),
            'points': None if score is None else float((score * PART_MAX / 100).quantize(Decimal('0.01'))),
            'max_points': PART_MAX, 'reason': reason}


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Invalid metric')
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Non-finite metric')
    return number


def score_funding(result):
    if result.get('status') != 'ok':
        status = 'stale' if result.get('status') in ('stale', 'settlement_time_passed') else 'unavailable'
        return _part(status, 'Для оценки требуется актуальная ставка Funding.')
    try:
        if result['unit'] != 'percent':
            raise ValueError('Expected percent units')
        rate, lower, upper = [_number(result[key]) for key in
                              ('funding_rate_pct', 'min_funding_rate_pct', 'max_funding_rate_pct')]
        if not lower <= 0 <= upper or not lower <= rate <= upper:
            raise ValueError('Invalid funding limits')
        score = Decimal(0) if rate == 0 else abs(rate) / (upper if rate > 0 else abs(lower)) * 100
        return _part('ok', 'Модуль ставки / модуль предела для её знака × 5. Это близость к пределу биржи, не историческая редкость.', score)
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return _part('invalid_data', 'Некорректная ставка или пределы Funding.')


def score_rsi(result):
    if result.get('status') != 'ok':
        status = result.get('status') if result.get('status') in ('stale', 'insufficient_data', 'invalid_data') else 'unavailable'
        return _part(status, 'Для оценки требуется корректный RSI 15 минут.')
    try:
        if result['interval'] != '15m' or result['period'] != 14 or result['method'] != 'wilder':
            raise ValueError('Unexpected RSI calculation')
        value = _number(result['rsi'])
        if not 0 <= value <= 100:
            raise ValueError('Invalid RSI')
        score = ((RSI_LOWER - value) / RSI_LOWER * 100 if value < RSI_LOWER
                 else (value - RSI_UPPER) / (100 - RSI_UPPER) * 100 if value > RSI_UPPER else Decimal(0))
        return _part('ok', 'RSI 30–70: 0 баллов; дальше к 0 или 100 вклад линейно возрастает до 5 баллов.', score)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return _part('invalid_data', 'Некорректный RSI 15 минут.')


def calculate_extras(funding, rsi):
    """Accept raw metric results; freshness and symbol alignment belong to the caller."""
    parts = {'funding': score_funding(funding), 'rsi': score_rsi(rsi)}
    ready = all(part['status'] == 'ok' for part in parts.values())
    status = 'ok' if ready else 'invalid_data' if any(part['status'] == 'invalid_data' for part in parts.values()) else 'insufficient_data'
    # Sum displayed sub-contributions so the breakdown agrees with the total.
    score = sum(Decimal(str(part['points'])) for part in parts.values()) * 10 if ready else None
    component = calculate_anomaly_score({'extras': {
        'status': status, 'score': score,
        'reason': 'Funding и RSI дают до 5 баллов каждый.' if ready else 'Для компонента нужны обе оценки: Funding и RSI.',
    }})['components']['extras']
    return {**component, 'version': VERSION, 'parts': parts}
