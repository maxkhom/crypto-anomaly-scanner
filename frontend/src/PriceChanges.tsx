import { useEffect, useState } from 'react'
import HourRelativeVolume from './HourRelativeVolume'
import OpenInterest from './OpenInterest'
import FundingRate from './FundingRate'

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
  minute_momentum: {
    minutes: (Metric & { from_time: string; to_time: string })[]
    change_pp: number | null
    status: string
    warning_count: number
  }
  relative_volume_15m: Result['relative_volume']
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
        if (!result.minute_momentum || !Array.isArray(result.minute_momentum.minutes) || result.minute_momentum.minutes.length !== 3 || result.symbol !== symbol || !result.relative_volume_15m || (result.relative_volume_15m.rvol !== null && !Number.isFinite(result.relative_volume_15m.rvol)) || !result.relative_volume || (result.relative_volume.rvol !== null && !Number.isFinite(result.relative_volume.rvol)) || !Number.isFinite(Date.parse(result.reference_time)) || !result.changes || periods.some((period) => {
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
        <div><h2>{symbol} · Цена и объём</h2><p>По завершённым свечам</p></div>
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
        <div className="momentum-panel">
          <h3>Минутный темп</h3>
          <p className="metric-note">Три последовательные закрытые минуты, от старой к новой.</p>
          <div className="momentum-grid">
            {data.minute_momentum.minutes.map((minute) => <div className="metric" key={minute.to_time}>
              <span>{new Date(minute.from_time).toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'})}–{new Date(minute.to_time).toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'})}</span>
              <strong className={minute.percent !== null && minute.percent > 0 ? 'positive' : minute.percent !== null && minute.percent < 0 ? 'negative' : ''}>{minute.status === 'ok' && minute.percent !== null ? `${format.format(minute.percent)}%` : '—'}</strong>
              {minute.status !== 'ok' && <small>{minute.status === 'insufficient_data' ? 'Недостаточно данных' : 'Некорректная цена'}</small>}
            </div>)}
            <div className="metric"><span>Изменение темпа</span><strong>{data.minute_momentum.status === 'ok' && data.minute_momentum.change_pp !== null ? `${format.format(data.minute_momentum.change_pp)} п.п.` : '—'}</strong>
              <small>Последняя минута минус предыдущая</small>
              {data.minute_momentum.status !== 'ok' && <small>Расчёт недоступен</small>}
            </div>
          </div>
          <p className="metric-note">Положительная разница означает усиление роста или замедление падения; отрицательная — усиление падения или замедление роста. При смене знака доходности оценивайте оба значения. Это не торговый сигнал.</p>
          {data.minute_momentum.warning_count > 0 && <p className="metric-note">Свечей с предупреждением об открытии в расчёте темпа: {data.minute_momentum.warning_count}. Используются проверенные цены закрытия.</p>}
        </div>
      </>}
      <OpenInterest key={`oi-${symbol}-${revision}`} symbol={symbol} />
      <FundingRate key={`funding-${symbol}-${revision}`} symbol={symbol} />
      {data && <>
        {([{minutes: 5, metric: data.relative_volume}, {minutes: 15, metric: data.relative_volume_15m}]).map(({minutes, metric}) => (
        <div className="rvol-panel" key={minutes}>
          <div>
            <h3>Relative Volume · {minutes} минут</h3>
            <strong className="rvol-value">{metric.status === 'ok' && metric.rvol !== null ? `${rvolFormat.format(metric.rvol)}x` : '—'}</strong>
            <p>1x — средний объём; выше 1x — выше среднего.</p>
          </div>
          <div className="rvol-details">
            <p>Последние {minutes} минут: <strong>{metric.current_volume_usdt === null ? 'нет данных' : `${volumeFormat.format(Number(metric.current_volume_usdt))} USDT`}</strong></p>
            <p>Среднее предыдущих 20 окон: <strong>{metric.baseline_average_volume_usdt === null ? 'нет данных' : `${volumeFormat.format(Number(metric.baseline_average_volume_usdt))} USDT`}</strong></p>
            <p>Окно: {new Date(metric.current_from).toLocaleTimeString('ru-RU')}–{new Date(metric.current_to).toLocaleTimeString('ru-RU')} (местное время)</p>
            {metric.status !== 'ok' && <p className="rvol-warning">{metric.reason === 'zero_baseline' ? 'Средний исторический объём равен нулю; RVOL не определён.' : metric.reason === 'missing_candles' ? `Недостаточно данных: отсутствует минут — ${metric.missing_count}.` : 'Некорректные данные объёма.'}</p>}
            {metric.warning_count > 0 && <p className="rvol-warning">Свечей с предупреждением об открытии: {metric.warning_count}. Объёмы прошли проверку.</p>}
          </div>
        </div>
        ))}
        {periods.some((period) => data.changes[period].warning_count > 0) && <p className="metric-note">У части свечей открытие вне диапазона. Расчёт выполнен по проверенным ценам закрытия.</p>}
        {data.source_rejected_count > 0 && <p className="notice">Отклонено свечей: {data.source_rejected_count}. Периоды с пропусками не рассчитываются.</p>}
      </>}
      <HourRelativeVolume key={`${symbol}-${revision}`} symbol={symbol} />
    </section>
  )
}
