import { useEffect, useState } from 'react'

type Window = { percent: number | null; status: string }
type Snapshot = {
  symbol: string
  status: string
  as_of: string
  last_trade: { price: string; time: string } | null
  seconds_since_last_trade_received: number | null
  received_trade_count: number
  short_momentum: { history?: { status: string; valid_intervals: number; required_intervals: number; percentile: number | null }; status: string; windows: Window[]; change_pp: number | null }
}
const format = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4, signDisplay: 'exceptZero' })
const states: Record<string, string> = {
  live: 'Сделки поступают', waiting: 'Ожидание сделок', stale: 'Данные устарели', disconnected: 'Нет соединения с биржей',
}

type Universe = { items: Snapshot[]; symbols: string[]; count: number; live_count: number; last_error: string | null }

export default function RealtimePanel() {
  const [symbol, setSymbol] = useState('')
  const [sort, setSort] = useState('strength')
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
  const rows = [...(universe?.items ?? [])].sort((a, b) => {
    if (sort === 'symbol') return a.symbol.localeCompare(b.symbol)
    const av = sort === 'unusual' ? unusualValue(a) : lastMove(a), bv = sort === 'unusual' ? unusualValue(b) : lastMove(b)
    if (av === null) return bv === null ? a.symbol.localeCompare(b.symbol) : 1
    if (bv === null) return -1
    const difference = sort === 'growth' || sort === 'unusual' ? bv - av : sort === 'fall' ? av - bv : Math.abs(bv) - Math.abs(av)
    return difference || a.symbol.localeCompare(b.symbol)
  })
  const selected = universe?.items.find((item) => item.symbol === symbol) ?? null
  return <div>
    <section className="panel price-panel" aria-label="Таблица быстрых движений">
      <div className="toolbar"><div><h2>Быстрые движения · весь список</h2><p>Обновление каждую секунду · интервалы по 10 секунд: от старого к новому</p></div>
        <label className="realtime-selector">Сортировка
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="unusual">Необычность цены</option><option value="strength">Сила движения</option><option value="growth">Рост</option>
            <option value="fall">Падение</option><option value="symbol">Монета</option>
          </select>
        </label>
      </div>
      {error && <p className="notice error" role="alert">Нет свежих данных backend. Повторяем подключение…</p>}
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Быстрые движения, доступна горизонтальная прокрутка">
        <table><thead><tr><th>Монета</th><th>Цена, USDT</th><th>Самый ранний · 10 с</th><th>Предыдущий · 10 с</th><th>Последний завершённый · 10 с</th><th>Темп, п.п.</th><th title="Доля предыдущих движений, которые последнее превысило по абсолютной величине">Необычность цены</th><th>Состояние</th></tr></thead>
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
            <td>{states[item.status]}<small>{item.status === 'live' && item.short_momentum.status === 'warming_up' ? 'Накапливаем историю' : item.status === 'live' && item.short_momentum.status === 'missing_data' ? 'Пропуски в расчётах' : ''}
              {item.seconds_since_last_trade_received !== null ? ` · Получено ${item.seconds_since_last_trade_received.toFixed(1)} с назад` : ''}</small></td>
          </tr>)}</tbody>
        </table>
        {!rows.length && <p className="empty">{error ? 'Данные временно недоступны' : 'Ожидаем список контрактов…'}</p>}
      </div>
      <p className="metric-note">Сила движения — абсолютное изменение последнего интервала. Необычность цены — доля движений предыдущих 30 минут, которые последнее превысило по модулю. Это не вероятность успеха сделки и ещё не Anomaly Score. Границы интервалов общие для всех монет: :00, :10, :20… Время определяется получением данных сервером.</p>
    </section>
    <p className="metric-note">{error ? 'Не удалось обновить список потоков. Повторяем запрос…'
      : universe?.count ? `Выбрано контрактов: ${universe.count}. Свежие сделки: ${universe.live_count}.`
        : 'Выбираем контракты для потока…'}
      {' '}До 20 контрактов по суточному объёму на момент запуска backend.
      {!error && universe?.last_error && ' Соединение восстанавливается автоматически.'}
    </p>
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
    {momentum?.history && <p className="metric-note">
      История для сравнения: {momentum.history.valid_intervals} / {momentum.history.required_intervals} корректных интервалов.
      {' '}{!live ? 'Оценка недоступна: нет свежих сделок.'
        : momentum.history.status === 'ok' && momentum.history.percentile !== null
          ? `Последнее движение сильнее ${momentum.history.percentile.toLocaleString('ru-RU')}% движений предыдущих 30 минут.`
          : momentum.history.status === 'warming_up' ? 'Накопление истории — требуется чуть больше 30 минут непрерывной работы.'
            : 'Недостаточно данных: есть пропуски в истории или последнем интервале.'}
      {' '}Равные по величине движения не считаются превышенными. После перезапуска backend история накапливается заново.
    </p>}
    <p className="metric-note">{live && momentum?.status === 'warming_up'
      ? 'Накапливаем историю: требуется около 40 секунд непрерывного потока.'
      : live && momentum?.status === 'missing_data' ? 'Для части интервалов недостаточно свежих цен.'
        : 'Три завершённых интервала от старого к новому. Время измеряется по получению данных сервером; задержка сети влияет на результат.'}
      {' '}Это изменение цены, а не оценка аномальности или торговый сигнал.
    </p>
  </section>
}
