import { useEffect, useState } from 'react'

type Window = { percent: number | null; status: string }
type Acceleration = {
  status: string; score: number | null; change_pp: number | null
  valid_samples: number; required_samples: number; reason: string
}
type Snapshot = {
  symbol: string
  status: string
  as_of: string
  last_trade: { price: string; time: string } | null
  seconds_since_last_trade_received: number | null
  received_trade_count: number
  short_momentum: {
    history?: { status: string; valid_intervals: number; required_intervals: number; percentile: number | null }
    price_acceleration?: Acceleration
    anomaly_score?: { components: { price_acceleration: { status: string; points: number | null; max_points: number } } }
    status: string; windows: Window[]; change_pp: number | null
  }
}
const format = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4, signDisplay: 'exceptZero' })
const states: Record<string, string> = {
  live: 'Сделки поступают', waiting: 'Ожидание сделок', stale: 'Данные устарели', disconnected: 'Нет соединения с биржей',
}

type Universe = { storage_error?: string | null; items: Snapshot[]; symbols: string[]; count: number; live_count: number; last_error: string | null }

export default function RealtimePanel() {
  const [symbol, setSymbol] = useState('')
  const [sort, setSort] = useState('strength')
  const [direction, setDirection] = useState('all')
  const [minMove, setMinMove] = useState(0)
  const [minUnusual, setMinUnusual] = useState(0)
  const [universe, setUniverse] = useState<Universe | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let controller: AbortController | undefined
    async function update() {
      controller = new AbortController()
      const timeout = setTimeout(() => controller?.abort(), 5000)
      try {
        const response = await fetch('/api/market/realtime/all', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('Недоступен список')
        const result: Universe = await response.json()
        if (!Array.isArray(result.symbols) || result.symbols.some((item) => typeof item !== 'string')
          || !Number.isInteger(result.live_count) || !Array.isArray(result.items) || result.items.some((item) => !validSnapshot(item))) throw new Error('Некорректный список')
        if (active) {
          setUniverse(result)
          setError(false)
          setSymbol((previous) => result.symbols.includes(previous) ? previous : result.symbols[0] ?? '')
        }
      } catch {
        if (active) { setError(true); setUniverse(null) }
      } finally {
        clearTimeout(timeout)
        if (active) timer = setTimeout(update, 1000)
      }
    }
    timer = setTimeout(update, 0)
    return () => { active = false; clearTimeout(timer); controller?.abort() }
  }, [])
  const rows = (universe?.items ?? []).filter((item) => {
    const move = lastMove(item)
    if (direction === 'up' && (move === null || move <= 0)) return false
    if (direction === 'down' && (move === null || move >= 0)) return false
    if (minMove > 0 && (move === null || Math.abs(move) < minMove)) return false
    const unusual = unusualValue(item)
    return minUnusual === 0 || (unusual !== null && unusual >= minUnusual)
  }).sort((a, b) => {
    if (sort === 'symbol') return a.symbol.localeCompare(b.symbol)
    const av = sort === 'acceleration' ? accelerationPoints(a) : sort === 'unusual' ? unusualValue(a) : lastMove(a)
    const bv = sort === 'acceleration' ? accelerationPoints(b) : sort === 'unusual' ? unusualValue(b) : lastMove(b)
    if (av === null) return bv === null ? a.symbol.localeCompare(b.symbol) : 1
    if (bv === null) return -1
    const difference = sort === 'growth' || sort === 'unusual' || sort === 'acceleration' ? bv - av : sort === 'fall' ? av - bv : Math.abs(bv) - Math.abs(av)
    return difference || a.symbol.localeCompare(b.symbol)
  })
  const readyMoves = (universe?.items ?? []).filter((item) => lastMove(item) !== null).length
  const readyUnusual = (universe?.items ?? []).filter((item) => unusualValue(item) !== null).length
  const needsMove = direction !== 'all' || minMove > 0
  const emptyMessage = error ? 'Данные временно недоступны'
    : !universe?.count ? 'Ожидаем список контрактов…'
      : needsMove && readyMoves === 0 ? 'Нет готовых изменений за последние 10 секунд: история накапливается, есть пропуски или данные устарели. Фильтр направления пока не может определить рост и падение.'
        : minUnusual > 0 && readyUnusual === 0 ? 'Нет готовых оценок необычности. Дождитесь накопления истории без пропусков или отключите порог необычности.'
          : 'Среди доступных расчётов нет монет, соответствующих фильтрам. Снизьте пороги или сбросьте фильтры.'
  const selected = universe?.items.find((item) => item.symbol === symbol) ?? null
  return <div>
    <section className="panel price-panel" aria-label="Таблица быстрых движений">
      <div className="toolbar"><div><h2>Быстрые движения · весь список</h2><p>Обновление каждую секунду · интервалы по 10 секунд: от старого к новому</p></div>
        <label className="realtime-selector">Сортировка
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="unusual">Необычность цены</option><option value="acceleration">Необычность ускорения</option><option value="strength">Сила движения</option><option value="growth">Рост</option>
            <option value="fall">Падение</option><option value="symbol">Монета</option>
          </select>
        </label>
      </div>
      <div className="scanner-filters">
        <label className="realtime-selector">Направление
          <select value={direction} onChange={(event) => setDirection(event.target.value)}>
            <option value="all">Все</option><option value="up">Только рост</option><option value="down">Только падение</option>
          </select>
        </label>
        <label className="realtime-selector">Движение за последние 10 с, по модулю
          <select value={minMove} onChange={(event) => setMinMove(Number(event.target.value))}>
            <option value={0}>Без ограничения</option>
            {[0.01, 0.05, 0.1, 0.5, 1].map((value) => <option key={value} value={value}>≥ {value.toLocaleString('ru-RU')}%</option>)}
          </select>
        </label>
        <label className="realtime-selector">Необычность цены
          <select value={minUnusual} onChange={(event) => setMinUnusual(Number(event.target.value))}>
            <option value={0}>Без ограничения</option>
            {[90, 95, 99].map((value) => <option key={value} value={value}>≥ {value}%</option>)}
          </select>
        </label>
        <button className="refresh" onClick={() => { setDirection('all'); setMinMove(0); setMinUnusual(0) }}>Сбросить фильтры</button>
      </div>
      <p className="metric-note">Показано {rows.length} из {universe?.count ?? 0}. Готовых изменений за 10 с: {readyMoves}. Готовых оценок необычности: {readyUnusual}. Фильтры применяются совместно к последнему завершённому интервалу.
        {minUnusual > 0 && ' Монеты без готовой оценки необычности скрыты; накопление истории продолжается.'}
      </p>
      {error && <p className="notice error" role="alert">Нет свежих данных backend. Повторяем подключение…</p>}
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Быстрые движения, доступна горизонтальная прокрутка">
        <table><thead><tr><th>Монета</th><th>Цена, USDT</th><th>Самый ранний · 10 с</th><th>Предыдущий · 10 с</th><th>Последний завершённый · 10 с</th><th>Темп, п.п.</th><th title="Доля предыдущих движений, которые последнее превысило по абсолютной величине">Необычность цены</th><th title="Вклад необычности изменения темпа в будущий Anomaly Score; максимум 25 баллов">Ускорение · /25</th><th>Состояние</th></tr></thead>
          <tbody>{rows.map((item) => <tr key={item.symbol}>
            <td><button className="symbol-button" aria-pressed={symbol === item.symbol} onClick={() => setSymbol(item.symbol)}>{item.symbol}</button></td>
            <td>{item.status === 'live' ? item.last_trade?.price ?? '—' : '—'}</td>
            {[0, 1, 2].map((index) => {
              const metric = item.short_momentum.windows[index]
              const value = item.status === 'live' && metric?.status === 'ok' ? metric.percent : null
              return <td key={index} className={value !== null && value > 0 ? 'positive' : value !== null && value < 0 ? 'negative' : ''}>{value === null ? '—' : `${format.format(value)}%`}</td>
            })}
            <td>{item.status === 'live' && item.short_momentum.change_pp !== null ? format.format(item.short_momentum.change_pp) : '—'}</td>
            <td><UnusualCell item={item} /></td>
            <td><AccelerationCell item={item} /></td>
            <td>{states[item.status]}<small>{item.status === 'live' && item.short_momentum.status === 'warming_up' ? 'Накапливаем историю' : item.status === 'live' && item.short_momentum.status === 'missing_data' ? 'Пропуски в расчётах' : ''}
              {item.seconds_since_last_trade_received !== null ? ` · Получено ${item.seconds_since_last_trade_received.toFixed(1)} с назад` : ''}</small></td>
          </tr>)}</tbody>
        </table>
        {!rows.length && <p className="empty">{emptyMessage}</p>}
      </div>
      <p className="metric-note">Сила движения — абсолютное изменение последнего интервала. Необычность цены — доля движений предыдущих 30 минут, которые последнее превысило по модулю. Это не вероятность успеха сделки и ещё не Anomaly Score. Границы интервалов общие для всех монет: :00, :10, :20… Время определяется получением данных сервером.</p>
      <p className="metric-note">Ускорение · /25 — отдельный компонент будущего Score: необычность разницы доходностей двух соседних интервалов. Сравнение с 180 предыдущими разницами по модулю. Высокое значение возможно при ускорении, замедлении или развороте, даже если движение мало по величине.</p>
    </section>
    <p className="metric-note">{error ? 'Не удалось обновить список потоков. Повторяем запрос…'
      : universe?.count ? `Выбрано контрактов: ${universe.count}. Свежие сделки: ${universe.live_count}.`
        : 'Выбираем контракты для потока…'}
      {' '}До 20 контрактов по суточному объёму на момент запуска backend.
      {!error && universe?.last_error && ' Соединение восстанавливается автоматически.'}
    </p>
    {universe?.storage_error && <p className="notice error">Не удалось прочитать или сохранить историю. Текущий поток работает, но сохранение истории требует проверки backend.</p>}
    {!!universe?.symbols.length && <label className="realtime-selector">Монета быстрого потока{' '}
      <select value={symbol} onChange={(event) => setSymbol(event.target.value)}>
        {universe.symbols.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
    </label>}
    {symbol && <RealtimeDetails symbol={symbol} data={selected} error={error ? "Нет свежих данных backend" : ""} />}
  </div>
}

function validSnapshot(item: Snapshot) {
  return item && typeof item.symbol === 'string' && !!states[item.status]
    && Number.isFinite(Date.parse(item.as_of)) && item.short_momentum
    && Array.isArray(item.short_momentum.windows)
    && item.short_momentum.windows.every((window) => window && (window.percent === null || Number.isFinite(window.percent)))
    && (item.short_momentum.change_pp === null || Number.isFinite(item.short_momentum.change_pp))
    && (item.seconds_since_last_trade_received === null || Number.isFinite(item.seconds_since_last_trade_received))
}

function unusualValue(item: Snapshot): number | null {
  const history = item.short_momentum.history
  const value = history?.percentile
  return item.status === 'live' && history?.status === 'ok'
    && typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100
    ? value : null
}

function accelerationPoints(item: Snapshot): number | null {
  const component = item.short_momentum.anomaly_score?.components?.price_acceleration
  return item.status === 'live' && item.short_momentum.price_acceleration?.status === 'ok'
    && component?.status === 'ok' && component.max_points === 25
    && typeof component.points === 'number' && Number.isFinite(component.points)
    && component.points >= 0 && component.points <= 25 ? component.points : null
}

function AccelerationCell({ item }: { item: Snapshot }) {
  const points = accelerationPoints(item)
  const metric = item.short_momentum.price_acceleration
  if (points !== null) return <span title={metric?.reason}>{points.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} / 25</span>
  if (item.status !== 'live') return <>—<small>Нет свежих сделок</small></>
  if (!metric) return <>—</>
  return <>—<small>{metric.status === 'warming_up' ? 'История' : 'Недостаточно данных'} {metric.valid_samples}/{metric.required_samples}</small></>
}

function UnusualCell({ item }: { item: Snapshot }) {
  const value = unusualValue(item)
  if (value !== null) return <span title={`Движение сильнее ${value}% предыдущих движений этой монеты`}>{value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%</span>
  const history = item.short_momentum.history
  if (item.status !== 'live') return <>—<small>Нет свежих сделок</small></>
  if (!history) return <>—<small>Нет истории</small></>
  if (history.status === 'warming_up') return <>История {history.valid_intervals}/{history.required_intervals}</>
  return <>—<small>Пропуски · история {history.valid_intervals}/{history.required_intervals}</small></>
}

function lastMove(item: Snapshot) {
  const window = item.short_momentum.windows[2]
  return item.status === 'live' && window?.status === 'ok' ? window.percent : null
}

function RealtimeDetails({ symbol, data, error }: { symbol: string; data: Snapshot | null; error: string }) {
  const live = !error && data?.status === 'live'
  const momentum = data?.short_momentum
  const showChange = live && momentum?.change_pp !== null && momentum?.change_pp !== undefined
  return <section className="panel price-panel" aria-label={`Поток ${symbol}`}>
    <div className="toolbar">
      <div><h2>{symbol} · Быстрые движения</h2><p>Поток сделок Bitunix · обновление панели каждую секунду</p></div>
      <span className={live ? 'positive' : 'realtime-status'} role="status">{error ? 'Нет свежих данных' : data ? states[data.status] : 'Подключение…'}</span>
    </div>
    {error && <p className="notice error">{error}</p>}
    <p className="price-reference">Последняя цена: <strong>{live && data.last_trade ? `${data.last_trade.price} USDT` : '—'}</strong>
      {live && data.last_trade && <> · Сделка в {new Date(data.last_trade.time).toLocaleTimeString('ru-RU')}</>}
    </p>
    <div className="momentum-grid">
      {[0, 1, 2].map((index) => {
        const item = momentum?.windows[index]
        const value = live && item?.status === 'ok' ? item.percent : null
        return <div className="metric" key={index}>
          <span>{['Самый ранний · 10 с', 'Предыдущий · 10 с', 'Последний завершённый · 10 с'][index]}</span>
          <strong className={value !== null && value > 0 ? 'positive' : value !== null && value < 0 ? 'negative' : ''}>{value !== null ? `${format.format(value)}%` : '—'}</strong>
        </div>
      })}
      <div className="metric"><span>Изменение темпа</span><strong>{showChange ? `${format.format(momentum!.change_pp!)} п.п.` : '—'}</strong><small>Последний интервал минус предыдущий</small></div>
    </div>
    {data && momentum?.price_acceleration && <div className="momentum-panel">
      <h3>Компонент Anomaly Score · Ускорение цены</h3>
      <div className="metric">
        <span>Вклад в будущий общий Score</span>
        <strong><AccelerationCell item={data} /></strong>
        <small>{live ? momentum.price_acceleration.reason : 'Нет свежих сделок: оценка недоступна.'}</small>
        <small>История: {momentum.price_acceleration.valid_samples} / {momentum.price_acceleration.required_samples} изменений темпа.</small>
      </div>
      <p className="metric-note">Оценка 95 из 100 означает 23,75 из 25 баллов компонента. Сравниваются модули изменения темпа; равные значения не считаются превышенными. Это относительный ранг, а не вероятность сделки. Общий Score появится после подключения остальных компонентов.</p>
    </div>}
    {momentum?.history && <p className="metric-note">
      История для сравнения: {momentum.history.valid_intervals} / {momentum.history.required_intervals} корректных интервалов.
      {' '}{!live ? 'Оценка недоступна: нет свежих сделок.'
        : momentum.history.status === 'ok' && momentum.history.percentile !== null
          ? `Последнее движение сильнее ${momentum.history.percentile.toLocaleString('ru-RU')}% движений предыдущих 30 минут.`
          : momentum.history.status === 'warming_up' ? 'Накопление истории — требуется чуть больше 30 минут непрерывной работы.'
            : 'Недостаточно данных: есть пропуски в истории или последнем интервале.'}
      {' '}Равные по величине движения не считаются превышенными. История сохраняется локально. Паузы в работе остаются пропусками.
    </p>}
    <p className="metric-note">{live && momentum?.status === 'warming_up'
      ? 'Накапливаем историю: требуется около 40 секунд непрерывного потока.'
      : live && momentum?.status === 'missing_data' ? 'Для части интервалов недостаточно свежих цен.'
        : 'Три завершённых интервала от старого к новому. Время измеряется по получению данных сервером; задержка сети влияет на результат.'}
      {' '}Это изменение цены, а не оценка аномальности или торговый сигнал.
    </p>
  </section>
}
