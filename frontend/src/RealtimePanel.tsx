import { useEffect, useState } from 'react'

type Window = { percent: number | null; status: string }
type Snapshot = {
  symbol: string
  status: string
  as_of: string
  last_trade: { price: string; time: string } | null
  received_trade_count: number
  short_momentum: { status: string; windows: Window[]; change_pp: number | null }
}
const format = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4, signDisplay: 'exceptZero' })
const states: Record<string, string> = {
  live: 'Сделки поступают', waiting: 'Ожидание сделок', stale: 'Данные устарели', disconnected: 'Нет соединения с биржей',
}

export default function RealtimePanel() {
  const [symbol, setSymbol] = useState('BTCUSDT')
  return <div>
    <label className="realtime-selector">Монета быстрого потока{' '}
      <select value={symbol} onChange={(event) => setSymbol(event.target.value)}>
        <option value="BTCUSDT">BTCUSDT</option>
        <option value="ETHUSDT">ETHUSDT</option>
      </select>
    </label>
    <RealtimeDetails key={symbol} symbol={symbol} />
  </div>
}

function RealtimeDetails({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let controller: AbortController | undefined
    async function update() {
      controller = new AbortController()
      const timeout = setTimeout(() => controller?.abort(), 5000)
      try {
        const response = await fetch(`/api/market/realtime?symbol=${encodeURIComponent(symbol)}`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const result: Snapshot = await response.json()
        if (result.symbol !== symbol || !states[result.status] || !Number.isFinite(Date.parse(result.as_of))
          || !result.short_momentum || !Array.isArray(result.short_momentum.windows)
          || result.short_momentum.windows.some((item) => !item || (item.percent !== null && !Number.isFinite(item.percent)))
          || (result.short_momentum.change_pp !== null && !Number.isFinite(result.short_momentum.change_pp))) {
          throw new Error('Некорректный ответ сервера')
        }
        if (active) { setData(result); setError('') }
      } catch {
        if (active) { setData(null); setError('Backend недоступен или вернул некорректный ответ. Повторяем подключение…') }
      } finally {
        clearTimeout(timeout)
        if (active) timer = setTimeout(update, 1000)
      }
    }
    timer = setTimeout(update, 0)
    return () => { active = false; clearTimeout(timer); controller?.abort() }
  }, [symbol])

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
          <span>{['Первый интервал · 10 с', 'Второй интервал · 10 с', 'Последний интервал · 10 с'][index]}</span>
          <strong className={value !== null && value > 0 ? 'positive' : value !== null && value < 0 ? 'negative' : ''}>{value !== null ? `${format.format(value)}%` : '—'}</strong>
        </div>
      })}
      <div className="metric"><span>Изменение темпа</span><strong>{showChange ? `${format.format(momentum!.change_pp!)} п.п.` : '—'}</strong><small>Последний интервал минус предыдущий</small></div>
    </div>
    <p className="metric-note">{live && momentum?.status === 'warming_up'
      ? 'Накапливаем историю: требуется около 40 секунд непрерывного потока.'
      : live && momentum?.status === 'missing_data' ? 'Для части интервалов недостаточно свежих цен.'
        : 'Три завершённых интервала от старого к новому. Время измеряется по получению данных сервером; задержка сети влияет на результат.'}
      {' '}Это изменение цены, а не оценка аномальности или торговый сигнал.
    </p>
  </section>
}
