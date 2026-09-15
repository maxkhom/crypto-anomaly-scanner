import { useEffect, useState } from 'react'

const periods = ['1m', '5m', '15m', '1h', '4h'] as const
const labels = { '1m': '1 минута', '5m': '5 минут', '15m': '15 минут', '1h': '1 час', '4h': '4 часа' }
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
  relative_volume: {
    rvol: number | null
    status: string
    reason: string | null
    current_volume_usdt: string | null
    baseline_average_volume_usdt: string | null
    missing_count: number
    warning_count: number
    current_from: string
    current_to: string
  }
}
const volumeFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const rvolFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4 })
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
    const timeout = setTimeout(() => controller.abort(), 35000)
    // Delay dispatch by one event-loop turn to avoid duplicate development effects.
    const start = setTimeout(async () => {
      try {
        const response = await fetch(`/api/scanner/metrics?symbol=${encodeURIComponent(symbol)}`, { signal: controller.signal })
        if (!response.ok) throw new Error(`Не удалось получить расчёты (HTTP ${response.status}). Повторите запрос.`)
        const result: Result = await response.json()
        if (result.symbol !== symbol || !result.relative_volume || (result.relative_volume.rvol !== null && !Number.isFinite(result.relative_volume.rvol)) || !Number.isFinite(Date.parse(result.reference_time)) || !result.changes || periods.some((period) => {
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
        <div><h2>{symbol} · Цена и объём</h2><p>По завершённым минутным свечам</p></div>
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
        <div className="rvol-panel">
          <div>
            <h3>Relative Volume · 5 минут</h3>
            <strong className="rvol-value">{data.relative_volume.status === 'ok' && data.relative_volume.rvol !== null ? `${rvolFormat.format(data.relative_volume.rvol)}x` : '—'}</strong>
            <p>1x — средний объём; выше 1x — выше среднего.</p>
          </div>
          <div className="rvol-details">
            <p>Последние 5 минут: <strong>{data.relative_volume.current_volume_usdt === null ? 'нет данных' : `${volumeFormat.format(Number(data.relative_volume.current_volume_usdt))} USDT`}</strong></p>
            <p>Среднее предыдущих 20 окон: <strong>{data.relative_volume.baseline_average_volume_usdt === null ? 'нет данных' : `${volumeFormat.format(Number(data.relative_volume.baseline_average_volume_usdt))} USDT`}</strong></p>
            <p>Окно: {new Date(data.relative_volume.current_from).toLocaleTimeString('ru-RU')}–{new Date(data.relative_volume.current_to).toLocaleTimeString('ru-RU')} (местное время)</p>
            {data.relative_volume.status !== 'ok' && <p className="rvol-warning">{data.relative_volume.reason === 'zero_baseline' ? 'Средний исторический объём равен нулю; RVOL не определён.' : data.relative_volume.reason === 'missing_candles' ? `Недостаточно данных: отсутствует минут — ${data.relative_volume.missing_count}.` : 'Некорректные данные объёма.'}</p>}
            {data.relative_volume.warning_count > 0 && <p className="rvol-warning">Свечей с предупреждением об открытии: {data.relative_volume.warning_count}. Объёмы прошли проверку.</p>}
          </div>
        </div>
        {periods.some((period) => data.changes[period].warning_count > 0) && <p className="metric-note">У части свечей открытие вне диапазона. Расчёт выполнен по проверенным ценам закрытия.</p>}
        {data.source_rejected_count > 0 && <p className="notice">Отклонено свечей: {data.source_rejected_count}. Периоды с пропусками не рассчитываются.</p>}
      </>}
    </section>
  )
}
