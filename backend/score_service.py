"""On-demand, multi-timeframe score snapshot. No background universe scan yet."""
import asyncio
import logging
import time
from datetime import datetime

from anomaly_score import calculate_anomaly_score
from bitunix import MarketDataError, iso_time, market_data
from extras_score import calculate_extras
from funding import get_funding
from open_interest import get_open_interest
from relative_volume import calculate_relative_volume
from rsi import calculate_rsi
from volatility import calculate_volatility

logger = logging.getLogger(__name__)
SOURCE_LIMIT = asyncio.Semaphore(4)


def _timestamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return int(stamp.timestamp() * 1000)


def _unavailable(reason, status='unavailable'):
    return {'status': status, 'score': None, 'reason': reason}


def _fresh(result, field, now, max_age):
    age = now - _timestamp(result[field])
    return 0 <= age <= max_age


def _metric(component):
    return {**component, 'score': component.get('normalized_score')}


def _check_source(source, symbol, exchange):
    if source.get('symbol') != symbol or source.get('exchange') != exchange:
        raise ValueError('Unexpected source or symbol')


def compose_score(symbol, now, sources, snapshot):
    """Pure composition; the caller takes the realtime snapshot on the event loop."""
    inputs, details = {}, {}

    def calculate(key, source, operation, exchange, observed_field=None, max_age=None):
        if source.get('status') == 'unavailable':
            inputs[key] = _unavailable(source.get('reason', 'Источник недоступен.'))
            details[key] = {'exchange': exchange}
            return
        try:
            _check_source(source, symbol, exchange)
            if observed_field and not _fresh(source, observed_field, now, max_age):
                inputs[key] = _unavailable('Данные источника устарели или имеют будущее время.', 'stale')
                details[key] = {'exchange': exchange, 'observed_at': source.get(observed_field)}
                return
            component, metadata = operation(source)
            inputs[key] = component
            details[key] = {'exchange': exchange, **metadata}
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            logger.warning('Invalid score source: symbol=%s component=%s: %s', symbol, key, exc)
            inputs[key] = _unavailable('Некорректные данные компонента.', 'invalid_data')
            details[key] = {'exchange': exchange}

    def acceleration(source):
        if source['status'] != 'live':
            return _unavailable('Нет свежего потока сделок.', 'stale'), {}
        component = source['short_momentum']['price_acceleration']
        if _timestamp(component['evaluated_to']) != now // 10000 * 10000:
            return _unavailable('Нет оценки последнего завершённого интервала.', 'stale'), {}
        return component, {'observed_at': component['evaluated_to'], 'period': '10s',
                           'version': component['version'], 'valid_samples': component['valid_samples'],
                           'required_samples': component['required_samples']}

    calculate('price_acceleration', snapshot, acceleration, 'bitunix', 'as_of', 15000)

    def candles(source, interval):
        if source['interval'] != interval:
            raise ValueError('Unexpected candle interval')
        return source['items']

    def volume(source):
        result = calculate_relative_volume(candles(source, '1m'), now)
        return _metric(result['score_component']), {
            'observed_at': result['current_to'], 'period': '5m', 'rvol': result['rvol'],
            'version': result['score_component']['version'],
            'warning_count': result['warning_count'], 'source_quality': source.get('data_quality'),
        }

    calculate('relative_volume', sources['minute'], volume, 'bitunix', 'as_of', 60000)

    def oi(source):
        if source['exchange'] not in ('bybit', 'binance'):
            raise ValueError('Unsupported OI exchange')
        return _metric(source['score_component']), {
            'observed_at': source['measured_at'], 'period': '5m',
            'version': source['score_component']['version'], 'unit': source['unit'],
            'definition': source.get('definition'), 'source_field': source.get('source_field'),
        }

    calculate('open_interest', sources['oi'], oi, sources['oi'].get('exchange'), 'measured_at', 600000)

    def volatility(source):
        result = calculate_volatility(candles(source, '15m'), now, '15m')
        return _metric(result['score_component']), {
            'observed_at': result['to_time'], 'period': '15m', 'atr_pct': result['atr_pct'],
            'version': result['score_component']['version'],
            'warning_count': result['warning_count'], 'source_quality': source.get('data_quality'),
        }

    calculate('volatility', sources['fifteen'], volatility, 'bitunix', 'as_of', 60000)

    def extras(source):
        rsi_source = sources['fifteen']
        if rsi_source.get('status') == 'unavailable':
            rsi = rsi_source
        else:
            _check_source(rsi_source, symbol, 'bitunix')
            rsi = (calculate_rsi(candles(rsi_source, '15m'), now, '15m')
                   if _fresh(rsi_source, 'as_of', now, 60000) else {'status': 'stale'})
        funding = source
        if _timestamp(source['next_funding_time']) <= now:
            funding = {**source, 'status': 'settlement_time_passed'}
        result = calculate_extras(funding, rsi)
        return _metric(result), {'version': result['version'], 'parts': result['parts'],
                                'funding_observed_at': source['fetched_at'],
                                'rsi_observed_at': rsi.get('to_time'), 'rsi_warning_count': rsi.get('warning_count', 0)}

    calculate('extras', sources['funding'], extras, 'bitunix', 'fetched_at', 60000)
    result = calculate_anomaly_score(inputs)
    for key, component in result['components'].items():
        component['details'] = details[key]
    return {'symbol': symbol, 'as_of': iso_time(now), 'model_version': 'cross_market_score_v2',
            'time_policy': 'latest_available_at_request_completion',
            'markets': ['bitunix'] + ([sources['oi']['exchange']] if sources['oi'].get('exchange') in ('bybit', 'binance') else []), **result}


async def get_score(symbol, stream):
    async def fetch(name, function, *args):
        try:
            async with SOURCE_LIMIT:
                return await asyncio.to_thread(function, *args)
        except Exception as exc:
            logger.warning('Score source failed: symbol=%s source=%s', symbol, name, exc_info=True)
            return {'status': 'unavailable', 'reason': str(exc) if isinstance(exc, MarketDataError)
                    else f'Источник {name} временно недоступен.'}

    minute, fifteen, oi, funding = await asyncio.gather(
        fetch('свечи 1m', market_data.get_candles, symbol, '1m', 107, True),
        fetch('свечи 15m', market_data.get_candles, symbol, '15m', 102, True),
        fetch('OI', get_open_interest, symbol),
        fetch('Funding', get_funding, symbol),
    )
    # Never read mutable realtime history from a worker thread.
    snapshot = stream.snapshot(symbol) if symbol in stream.states else _unavailable(
        'Монета не входит в текущий список потоков. Ускорение недоступно.')
    now = time.time_ns() // 1_000_000
    return compose_score(symbol, now, {'minute': minute, 'fifteen': fifteen, 'oi': oi, 'funding': funding}, snapshot)
