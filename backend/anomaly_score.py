"""Combine normalized component scores; raw market metrics must be normalized first.

This module does not define the normalization rules or fetch market data.
An input score is in [0, 100], never an RSI, return, funding rate or RVOL.
Callers must mark stale or otherwise unusable inputs with a non-ok status.
"""
from collections.abc import Mapping
from decimal import Decimal


AGGREGATION_VERSION = 'weighted_components_v1'
COMPONENTS = (
    ('price_acceleration', 'Ускорение цены', 25),
    ('relative_volume', 'Относительный объём', 25),
    ('open_interest', 'Изменение OI', 25),
    ('volatility', 'Волатильность', 15),
    ('extras', 'Экстремумы Funding / RSI', 10),
)
UNAVAILABLE_STATUSES = {
    'unavailable', 'insufficient_data', 'warming_up', 'stale', 'invalid_data',
}


def calculate_anomaly_score(components):
    """Return a complete 0–100 score, or null plus the missing contributions.

Each component is a mapping: status, score (normalized 0–100), reason.
Missing components are unavailable, not zero. No weight redistribution occurs.
Coverage is the sum of usable weights, not a confidence or success probability.
"""
    if not isinstance(components, Mapping):
        raise ValueError('Components must be a mapping')
    unknown = set(components) - {key for key, _, _ in COMPONENTS}
    if unknown:
        raise ValueError('Unknown score component')

    breakdown = {}
    coverage = 0
    total = Decimal(0)
    for key, label, weight in COMPONENTS:
        supplied = components.get(key)
        normalized = None
        points = None
        status = 'unavailable'
        reason = 'Компонент ещё не рассчитан.'
        if supplied is not None:
            if not isinstance(supplied, Mapping):
                status, reason = 'invalid_data', 'Некорректный формат компонента.'
            else:
                status = supplied.get('status')
                reason = supplied.get('reason')
                if not isinstance(reason, str) or not reason.strip():
                    reason = 'Компонент недоступен.'
                if status == 'ok':
                    value = supplied.get('score')
                    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                        status, reason = 'invalid_data', 'Ожидается нормализованная оценка от 0 до 100.'
                    else:
                        number = Decimal(str(value))
                        if not number.is_finite() or not 0 <= number <= 100:
                            status, reason = 'invalid_data', 'Оценка должна быть конечным числом от 0 до 100.'
                        else:
                            normalized = float(number)
                            contribution = (number * weight / 100).quantize(Decimal('0.01'))
                            points = float(contribution)
                            total += contribution
                            coverage += weight
                            if reason == 'Компонент недоступен.':
                                reason = 'Нормализованная оценка учтена.'
                elif not isinstance(status, str) or status not in UNAVAILABLE_STATUSES:
                    status, reason = 'invalid_data', 'Неизвестный статус компонента.'
        breakdown[key] = {
            'label': label, 'status': status, 'normalized_score': normalized,
            'points': points, 'max_points': weight, 'reason': reason,
        }

    missing = [key for key, row in breakdown.items() if row['status'] != 'ok']
    status = 'ok' if not missing else 'incomplete' if coverage else 'unavailable'
    if any(row['status'] == 'invalid_data' for row in breakdown.values()):
        status = 'invalid_data'
    return {
        'aggregation_version': AGGREGATION_VERSION,
        'score': float(total) if not missing else None,
        'status': status, 'coverage_pct': coverage,
        'missing_components': missing, 'components': breakdown,
    }
