import { useEffect, useState } from 'react'

const periods = ['1m', '5m', '15m', '1h'] as const
const labels = { '1m': '1 минута', '5m': '5 минут', '15m': '15 минут', '1h': '1 час' }
type Metric = {
  percent: number | null
  status: string
  missing_count: number
  warning_count: number
}
type Result = {
  symbol: string
  reference_time: string
  reference_price: string | null
  source_rejected_count: number
  changes: Record<typeof periods[number], Metric>
}
const format = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2, maximumFractionDigits: 4, signDisplay: 'exceptZero',
})

export default function PriceChanges({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 25000)
    // Delay dispatch by one event-loop turn to avoid duplicate development effects.
    const start = setTimeout(async () => {
      try {
        const response = await fetch(`/api/scanner/price-changes?symbol=${encodeURIComponent(symbol)}`, { signal: controller.signal })
        if (!response.ok) throw new Error(`Не удалось получить расчёты (HTTP ${response.status}). Повторите запрос.`)
        const result: Result = await response.json()
        if (result.symbol !== symbol || !Number.isFinite(Date.parse(result.reference_time)) || !result.changes || periods.some((period) => {
          const metric = result.changes[period]
          return !metric || (metric.percent !== null && !Number.isFinite(metric.percent))
        })) throw new Error('Неожиданный формат ответа сервера.')
        if (active) setData(result)
      } catch (reason) {
        if (active) setError(reason instanceof Error && reason.name === 'AbortError'
          ? 'Время ожидания истекло. Повторите запрос.'
          : reason instanceof Error ? reason.message : 'Не удалось загрузить расчёты.')
      } finally {
        clearTimeout(timeout)
        if (active) setLoading(false)
      }
    }, 0)
    return () => { active = false; clearTimeout(start); clearTimeout(timeout); controller.abort() }
  }, [symbol, revision])

  function refresh() {
    setData(null)
    setError('')
    setLoading(true)
    setRevision((value) => value + 1)
  }

  return (
    <section className="panel price-panel" aria-label={`Изменения цены ${symbol}`} aria-busy={loading}>
      <div className="toolbar">
        <div><h2>{symbol} · Изменения цены</h2><p>По закрытиям минутных свечей</p></div>
        <div className="controls">
          <button className="refresh" disabled={loading} onClick={refresh}>{loading ? 'Загрузка…' : 'Обновить расчёты'}</button>
          <button className="close-panel" onClick={onClose} aria-label="Закрыть панель монеты">×</button>
        </div>
      </div>
      {loading && <p className="empty" role="status">Получаем историю {symbol}…</p>}
      {error && <p className="notice error" role="alert">{error}</p>}
      {data && <>
        <p className="price-reference">Закрытие: <strong>{data.reference_price === null ? 'нет данных' : `${data.reference_price} USDT`}</strong> · На {new Date(data.reference_time).toLocaleString('ru-RU')} (местное время)</p>
        <div className="metric-grid">
          {periods.map((period) => {
            const metric = data.changes[period]
            const usable = metric.status === 'ok' && metric.percent !== null
            return <div className="metric" key={period}>
              <span>{labels[period]}</span>
              <strong className={usable && metric.percent! > 0 ? 'positive' : usable && metric.percent! < 0 ? 'negative' : ''}>{usable ? `${format.format(metric.percent!)}%` : '—'}</strong>
              {!usable && <small>{metric.status === 'insufficient_data' ? `Недостаточно данных: отсутствует закрытий — ${metric.missing_count}` : 'Некорректные данные'}</small>}
              {metric.warning_count > 0 && <small>Предупреждений о свечах: {metric.warning_count}</small>}
            </div>
          })}
        </div>
        {periods.some((period) => data.changes[period].warning_count > 0) && <p className="metric-note">У части свечей открытие вне диапазона. Расчёт выполнен по проверенным ценам закрытия.</p>}
        {data.source_rejected_count > 0 && <p className="notice">Отклонено свечей: {data.source_rejected_count}. Периоды с пропусками не рассчитываются.</p>}
      </>}
    </section>
  )
}
