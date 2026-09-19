import { useEffect, useState } from 'react'

const periods = ['5m', '15m', '1h'] as const
const labels = { '5m': '5 минут', '15m': '15 минут', '1h': '1 час' }
type Result = {
  exchange: string; symbol: string; unit: string; definition: string
  open_interest: string; status: string; measured_at: string
  changes: Record<typeof periods[number], { percent: number | null; status: string; from_time: string; to_time: string }>
}
const percent = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4, signDisplay: 'exceptZero' })

export default function OpenInterest({ symbol }: { symbol: 'BTCUSDT' | 'ETHUSDT' }) {
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    const start = setTimeout(async () => {
      try {
        const response = await fetch(`/api/scanner/open-interest?symbol=${encodeURIComponent(symbol)}`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error(`OI Bybit недоступен (HTTP ${response.status}).`)
        const result: Result = await response.json()
        if (result.exchange !== 'bybit' || result.symbol !== symbol || result.unit !== (symbol === 'BTCUSDT' ? 'BTC' : 'ETH')
          || result.definition !== 'sum_of_both_sides' || !['ok', 'stale'].includes(result.status)
          || !Number.isFinite(Number(result.open_interest)) || Number(result.open_interest) < 0
          || !Number.isFinite(Date.parse(result.measured_at)) || !result.changes
          || periods.some((period) => !result.changes[period]
            || (result.changes[period].percent !== null && !Number.isFinite(result.changes[period].percent)))) {
          throw new Error('Некорректный ответ OI Bybit.')
        }
        if (active) setData(result)
      } catch (reason) {
        if (active) setError(reason instanceof Error && reason.name === 'AbortError' ? 'Время ожидания OI Bybit истекло.' : reason instanceof Error ? reason.message : 'OI недоступен.')
      } finally { clearTimeout(timeout) }
    }, 0)
    return () => { active = false; clearTimeout(start); clearTimeout(timeout); controller.abort() }
  }, [revision, symbol])
  return <div className="momentum-panel">
    <h3>Open Interest · Bybit · {symbol}</h3>
    <p className="metric-note">Объём открытых позиций на Bybit. Это другой рынок, чем цены и объёмы Bitunix выше. Данные с шагом 5 минут; обновление — кнопкой «Обновить расчёты».</p>
    {!data && !error && <p className="price-reference" role="status">Получаем OI Bybit…</p>}
    {error && <div className="notice error" role="alert">{error} <button className="refresh" onClick={() => { setData(null); setError(''); setRevision((value) => value + 1) }}>Повторить</button></div>}
    {data && <>
      <p className="price-reference">Последнее измерение: <strong>{Number(data.open_interest).toLocaleString('ru-RU', { maximumFractionDigits: 8 })} {data.unit}</strong> · {new Date(data.measured_at).toLocaleString('ru-RU')} (местное время)</p>
      {data.status === 'stale' && <p className="notice">Bybit вернул устаревшее измерение. Изменения недоступны.</p>}
      <div className="momentum-grid">
        {periods.map((period) => {
          const metric = data.changes[period]
          const value = data.status === 'ok' && metric.status === 'ok' ? metric.percent : null
          return <div className="metric" key={period}><span>Изменение OI · {labels[period]}</span>
            <strong>{value === null ? '—' : `${percent.format(value)}%`}</strong>
            {value === null && <small>{metric.status === 'zero_baseline' ? 'Начальное значение OI равно нулю' : 'Недостаточно актуальных данных'}</small>}
          </div>
        })}
      </div>
      <p className="metric-note">Используется сумма обеих сторон по определению Bybit. Рост OI означает увеличение открытого интереса, но сам по себе не определяет направление цены.</p>
    </>}
  </div>
}
