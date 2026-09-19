"""Strict empirical rank of the absolute change between consecutive 10s returns."""
from decimal import Decimal

BASELINE_COUNT = 180


def calculate_price_acceleration(returns, live, warming_up):
    """Input: 182 chronological, unrounded percentage returns, including current.

180 historical adjacent differences precede the evaluated difference. Pairs
overlap; this is a descriptive rank, not an independent statistical test.
"""
    if len(returns) != BASELINE_COUNT + 2:
        raise ValueError('Expected 182 returns')
    result = {'version': 'acceleration_rank_10s_v1', 'status': 'unavailable',
              'score': None, 'change_pp': None, 'required_samples': BASELINE_COUNT,
              'valid_samples': 0, 'missing_samples': BASELINE_COUNT,
              'reason': 'Нет свежего потока сделок.'}
    values = []
    for value in returns:
        if value is None:
            values.append(None)
        elif isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            return {**result, 'status': 'invalid_data', 'reason': 'Некорректная доходность.'}
        else:
            number = Decimal(str(value))
            if not number.is_finite():
                return {**result, 'status': 'invalid_data', 'reason': 'Некорректная доходность.'}
            values.append(number)
    differences = [None if left is None or right is None else right - left
                   for left, right in zip(values, values[1:])]
    baseline = [value for value in differences[:-1] if value is not None]
    current = differences[-1]
    result.update(valid_samples=len(baseline), missing_samples=BASELINE_COUNT - len(baseline))
    if not live:
        return result
    if current is not None:
        result['change_pp'] = float(round(current, 6))
    if len(baseline) != BASELINE_COUNT or current is None:
        return {**result, 'status': 'warming_up' if warming_up else 'insufficient_data',
                'reason': 'История накапливается.' if warming_up else 'Есть пропуски в истории или последних двух интервалах.'}
    rank = round(100 * sum(abs(value) < abs(current) for value in baseline) / BASELINE_COUNT, 2)
    return {**result, 'status': 'ok', 'score': rank,
            'reason': f'Модуль изменения темпа превышает {rank:g}% из 180 предыдущих значений. Равные значения не считаются превышенными.'}
