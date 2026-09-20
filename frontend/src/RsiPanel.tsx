import { useEffect, useState } from 'react'

type Result = {
  symbol: string; interval: string; period: number; method: string
  rsi: number | null; status: string; to_time: string
  missing_count: number; warning_count: number
  score_part?: { status: string; points: number | null; max_points: number; reason: string }
}
function RsiMetric({ symbol, interval }: { symbol: string; interval: '15m' | '1h' }) {
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 25000)
    const start = setTimeout(async () => {
      try {
        const response = await fetch(`/api/scanner/rsi?symbol=${encodeURIComponent(symbol)}&interval=${interval}`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error(`RSI недоступен (HTTP ${response.status}).`)
        const result: Result = await response.json()
        if (result.symbol !== symbol || result.interval !== interval || result.period !== 14 || result.method !== 'wilder'
          || !['ok', 'insufficient_data', 'invalid_data'].includes(result.status)
          || !Number.isFinite(Date.parse(result.to_time))
          || (result.rsi !== null && (!Number.isFinite(result.rsi) || result.rsi < 0 || result.rsi > 100))
          || (result.status === 'ok' && result.rsi === null)) throw new Error('Некорректный ответ RSI.')
        if (active) setData(result)
      } catch (reason) {
        if (active) setError(reason instanceof Error && reason.name === 'AbortError' ? 'Время ожидания RSI истекло.' : reason instanceof Error ? reason.message : 'RSI недоступен.')
      } finally { clearTimeout(timeout) }
    }, 0)
    return () => { active = false; clearTimeout(start); clearTimeout(timeout); controller.abort() }
  }, [symbol, interval, revision])
  const value = data?.status === 'ok' ? data.rsi : null
  return <div className="metric">
    <span>RSI(14) · {interval === '15m' ? '15 минут' : '1 час'}</span>
    <strong>{value !== null ? value.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : '—'}</strong>
    {!data && !error && <small role="status">Загрузка…</small>}
    {error && <><small role="alert">{error}</small><button className="refresh" onClick={() => { setError(''); setData(null); setRevision((value) => value + 1) }}>Повторить</button></>}
    {value !== null && <small>{value >= 70 ? 'Зона ≥70' : value <= 30 ? 'Зона ≤30' : 'Между 30 и 70'}</small>}
    {interval === '15m' && data?.score_part && <>
      <small>RSI · вклад в Extras</small>
      <strong>{data.status === 'ok' && data.score_part.status === 'ok'
        && typeof data.score_part.points === 'number' && Number.isFinite(data.score_part.points)
        && data.score_part.points >= 0 && data.score_part.points <= 5 && data.score_part.max_points === 5
        ? `${data.score_part.points.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} / 5` : '—'}</strong>
      <small>{data.score_part.reason}</small>
    </>}
    {data && <>
      <small>Закрытие: {new Date(data.to_time).toLocaleString('ru-RU')}</small>
      {data.status !== 'ok' && <small>{data.status === 'insufficient_data' ? `Отсутствует закрытий: ${data.missing_count}` : 'Некорректные цены закрытия'}</small>}
      {data.warning_count > 0 && <small>Предупреждений о свечах: {data.warning_count}. Используются проверенные закрытия.</small>}
    </>}
  </div>
}

export default function RsiPanel({ symbol }: { symbol: string }) {
  return <div className="momentum-panel">
    <h3>RSI · Bitunix</h3>
    <div className="rsi-grid">
      <RsiMetric key={`${symbol}-15m`} symbol={symbol} interval="15m" />
      <RsiMetric key={`${symbol}-1h`} symbol={symbol} interval="1h" />
    </div>
    <p className="metric-note">RSI(14), сглаживание Уайлдера, история 100 закрытий. Шкала от 0 до 100; отметки 30 и 70 — ориентиры. Достижение этих уровней не подтверждает разворот. Обновление — кнопкой «Обновить расчёты».</p>
    <p className="metric-note">Extras — дополнительный компонент будущего Score: Funding до 5 баллов и RSI 15 минут до 5 баллов. Предварительные правила, не исторические ранги. Например, RSI 15 или 85 даёт 2,5/5. Часовой RSI остаётся дополнительным показателем; его баллы повторно не добавляются.</p>
  </div>
}
