"""Initial observation rule, not a trading setup."""
from decimal import Decimal
from datetime import datetime, timezone

RULE_VERSION = 'price_10s_v1'
MIN_PERCENTILE = 95
MIN_MOVE = Decimal('0.1')


def detect_event(symbol, momentum, now, live, reference_price=None):
    result = momentum.calculate(now, live)
    history = result['history']
    if not live or history['status'] != 'ok' or history['percentile'] < MIN_PERCENTILE:
        return None
    end = int(datetime.fromisoformat(history['evaluated_to']).timestamp())
    prices = dict(momentum.boundaries)
    opening, closing = prices.get(end - 10), prices.get(end)
    if opening is None or closing is None:
        return None
    change = (closing / opening - 1) * 100
    if abs(change) < MIN_MOVE:
        return None
    return {'rule_version': RULE_VERSION, 'exchange': 'bitunix', 'symbol': symbol,
            'interval_start': history['evaluated_from'], 'interval_end': history['evaluated_to'],
            'detected_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
            'start_price': str(opening), 'end_price': str(closing),
            'reference_price': reference_price, 'change_pct': float(change),
            'percentile': history['percentile'], 'baseline_intervals': 180,
            'baseline_from': history['baseline_from'], 'baseline_to': history['baseline_to'],
            'direction': 'up' if change > 0 else 'down',
            'event_type': 'ANOMALOUS_RISE' if change > 0 else 'ANOMALOUS_FALL',
            'time_basis': result['time_basis'],
            'min_percentile': MIN_PERCENTILE, 'min_abs_change_pct': str(MIN_MOVE)}
