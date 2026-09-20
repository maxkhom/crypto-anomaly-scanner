"""OI from Bybit, with Binance fallback for unmatched contracts only."""
import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from decimal import Decimal
from urllib.request import urlopen

from bitunix import MarketDataError, iso_time, market_data
from anomaly_score import calculate_anomaly_score

STEP = 300_000
logger = logging.getLogger(__name__)
SUPPORTED_UNITS = {'BTCUSDT': 'BTC', 'ETHUSDT': 'ETH'}
SCORE_WINDOWS = 20


def _oi_score(points, latest, stale, exchange):
    times = list(range(latest - (SCORE_WINDOWS + 1) * STEP, latest + 1, STEP))
    missing = sum(stamp not in points for stamp in times)
    score = None
    exceeded = None
    if stale:
        status, reason = 'stale', 'Последнее измерение OI устарело.'
    elif missing:
        status, reason = 'insufficient_data', f'Для оценки OI отсутствует измерений: {missing}.'
    elif any(points[stamp] == 0 for stamp in times[:-1]):
        status, reason = 'insufficient_data', 'Нельзя рассчитать процентное изменение OI от нулевого значения.'
    else:
        changes = [(points[right] / points[left] - 1) * 100 for left, right in zip(times, times[1:])]
        exceeded = sum(abs(value) < abs(changes[-1]) for value in changes[:-1])
        score = 100 * exceeded / SCORE_WINDOWS
        status = 'ok'
        reason = f'Модуль изменения OI за 5 минут больше {exceeded} из 20 предыдущих изменений. Равные значения не считаются превышенными.'
    component = calculate_anomaly_score({'open_interest': {
        'status': status, 'score': score, 'reason': reason,
    }})['components']['open_interest']
    return {**component, 'version': 'oi_change_rank_5m_v1', 'exchange': exchange,
            'exceeded_windows': exceeded, 'required_windows': SCORE_WINDOWS,
            'missing_snapshots': missing, 'evaluated_from': iso_time(latest - STEP),
            'evaluated_to': iso_time(latest), 'baseline_from': iso_time(times[0]),
            'baseline_to': iso_time(latest - STEP)}


def calculate_open_interest(payload, symbol="BTCUSDT", unit=None):
    unit = unit or SUPPORTED_UNITS.get(symbol)
    if not unit:
        raise ValueError("Unverified OI contract")
    if payload['retCode'] != 0:
        raise ValueError('Bybit rejected the request')
    source = payload['result']
    if source['symbol'] != symbol or source['category'] != 'linear':
        raise ValueError('Unexpected Bybit contract')
    return _calculate_history(source['list'], int(payload['time']), symbol, unit,
                              'bybit', 'openInterest', 'sum_of_both_sides')


def _calculate_history(rows, now, symbol, unit, exchange, field, definition):
    if now <= 0:
        raise ValueError('Invalid server time')
    points = {}
    for row in rows:
        timestamp = int(row['timestamp'])
        value = Decimal(row[field])
        if timestamp <= 0 or timestamp % STEP or timestamp > now or not value.is_finite() or value < 0:
            raise ValueError('Invalid OI snapshot')
        if timestamp in points and points[timestamp] != value:
            raise ValueError('Conflicting OI snapshots')
        points[timestamp] = value
    if not points:
        raise ValueError('No OI snapshots')
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
    return {'exchange': exchange, 'symbol': symbol, 'category': 'linear', 'unit': unit,
            'definition': definition, 'source_field': field,
            'open_interest': str(current), 'status': 'stale' if stale else 'ok',
            'measured_at': iso_time(latest), 'source_server_time': iso_time(now),
            'age_seconds': round((now - latest) / 1000, 3), 'interval': '5min', 'changes': changes,
            'score_component': _oi_score(points, latest, stale, exchange)}


def bybit_request(endpoint, **params):
    url = 'https://api.bybit.com/v5/market/' + endpoint + '?' + urlencode(params)
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise MarketDataError(f'Bybit: HTTP {exc.code} при запросе {endpoint}.') from exc
    except (URLError, TimeoutError) as exc:
        raise MarketDataError(f'Bybit: ошибка соединения или тайм-аут при запросе {endpoint}.') from exc
    if payload['retCode'] != 0:
        code = payload['retCode']
        if not isinstance(code, int):
            raise ValueError('Invalid Bybit return code')
        raise MarketDataError(f'Bybit отклонил запрос {endpoint}: retCode={code}.')
    return payload


def match_contract(payload, symbol, base):
    result = payload['result']
    if result['category'] != 'linear' or not isinstance(result['list'], list):
        raise ValueError('Invalid instruments response')
    matches = [row for row in result['list'] if row['symbol'] == symbol]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('Duplicate instrument')
    row = matches[0]
    if (row.get('contractType') != 'LinearPerpetual' or row.get('status') != 'Trading'
            or row.get('quoteCoin') != 'USDT' or row.get('settleCoin') != 'USDT'
            or row.get('baseCoin') != base or row.get('isPreListing', False)):
        return None
    # Multiplier contracts require an explicit unit mapping before support.
    if symbol != base + 'USDT':
        return None
    return row['baseCoin']


def get_open_interest(symbol="BTCUSDT"):
    if not re.fullmatch(r'[A-Z0-9]{2,40}USDT', symbol):
        raise ValueError('Invalid symbol')
    unavailable = {'exchange': 'bybit', 'symbol': symbol, 'status': 'unavailable',
                   'reason': 'Нет подтверждённого соответствующего активного USDT perpetual-контракта Bybit.'}
    stage = 'список контрактов Bitunix'
    try:
        instrument = next((row for row in market_data.get_active_usdt_futures() if row['symbol'] == symbol), None)
        if instrument is None:
            return unavailable
        stage = 'сопоставление контракта Bybit'
        metadata = bybit_request('instruments-info', category='linear', symbol=symbol)
        unit = match_contract(metadata, symbol, instrument['base'])
        if unit is None:
            stage = 'резервный источник Binance'
            return get_binance_open_interest(symbol, instrument['base'])
        stage = 'история OI Bybit'
        payload = bybit_request('open-interest', category='linear', symbol=symbol, intervalTime='5min', limit=SCORE_WINDOWS + 2)
        if not payload['result']['list']:
            return {**unavailable, 'reason': 'Bybit пока не вернул историю OI для этого контракта.'}
        return calculate_open_interest(payload, symbol, unit)
    except MarketDataError:
        logger.warning('OI source failed: symbol=%s; stage=%s', symbol, stage, exc_info=True)
        raise
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        logger.warning('OI validation failed: symbol=%s; stage=%s', symbol, stage, exc_info=True)
        raise MarketDataError(f'Некорректные данные OI; этап: {stage}. Подробности в логах сервера.') from exc


def binance_request(endpoint, **params):
    url = 'https://fapi.binance.com' + endpoint + '?' + urlencode(params)
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise MarketDataError(f'Binance: HTTP {exc.code} при запросе {endpoint}.') from exc
    except (URLError, TimeoutError) as exc:
        raise MarketDataError(f'Binance: ошибка соединения или тайм-аут при запросе {endpoint}.') from exc
    if isinstance(payload, dict) and 'code' in payload:
        raise MarketDataError(f"Binance отклонил запрос {endpoint}: code={payload['code']}.")
    return payload


def match_binance_contract(payload, symbol, base):
    matches = [row for row in payload['symbols'] if row['symbol'] == symbol]
    if len(matches) > 1:
        raise ValueError('Duplicate Binance instrument')
    if not matches or symbol != base + 'USDT':
        return None
    row = matches[0]
    if (row.get('contractType') != 'PERPETUAL' or row.get('status') != 'TRADING'
            or row.get('baseAsset') != base or row.get('quoteAsset') != 'USDT'
            or row.get('marginAsset') != 'USDT'):
        return None
    return base


def calculate_binance_open_interest(rows, now, symbol, unit):
    if not unit or not isinstance(rows, list) or any(row['symbol'] != symbol for row in rows):
        raise ValueError('Unexpected Binance contract')
    return _calculate_history(rows, now, symbol, unit, 'binance',
                              'sumOpenInterest', 'exchange_reported_open_interest')


def get_binance_open_interest(symbol, base):
    unavailable = {'exchange': 'binance', 'symbol': symbol, 'status': 'unavailable',
                   'reason': 'Нет подтверждённого соответствующего активного USDT perpetual-контракта на Bybit и Binance.'}
    # Multiplier contracts remain unsupported until explicit mappings are verified.
    if symbol != base + 'USDT':
        return unavailable
    metadata = binance_request('/fapi/v1/exchangeInfo')
    unit = match_binance_contract(metadata, symbol, base)
    if unit is None:
        return unavailable
    rows = binance_request('/futures/data/openInterestHist', symbol=symbol, period='5m', limit=SCORE_WINDOWS + 2)
    if not rows:
        return {**unavailable, 'reason': 'Binance пока не вернул историю OI для этого контракта.'}
    now = int(binance_request('/fapi/v1/time')['serverTime'])
    result = calculate_binance_open_interest(rows, now, symbol, unit)
    return {**result, 'selection_reason': 'no_matching_bybit_contract'}
