import { useEffect, useState } from 'react'

type Result = {
  symbol: string; interval: string; period: number; method: string; unit: string
  status: string; atr: string | null; atr_pct: number | null
  range_14: string | null; range_14_pct: number | null
  to_time: string; range_from: string; range_to: string
  missing_count: number; warning_count: number; source_rejected_count: number
  score_component?: {
    status: string; points: number | null; max_points: number; reason: string
    baseline_first_at: string; baseline_last_at: string
  }
}
const amount = (value: string) => Number(value).toLocaleString('ru-RU', { maximumSignificantDigits: 6 })
const percent = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 6 })
const date = (value: string) => new Date(value).toLocaleString('ru-RU')

function VolatilityMetric({ symbol, interval }: { symbol: string; interval: '15m' | '1h' }) {
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 25000)
    const start = setTimeout(async () => {
      try {
        const response = await fetch(`/api/scanner/volatility?symbol=${encodeURIComponent(symbol)}&interval=${interval}`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error(`Волатильность недоступна (HTTP ${response.status}).`)
        const result: Result = await response.json()
        if (result.symbol !== symbol || result.interval !== interval || result.period !== 14
          || result.method !== 'wilder' || result.unit !== 'USDT'
          || !['ok', 'insufficient_data', 'invalid_data'].includes(result.status)
          || [result.to_time, result.range_from, result.range_to].some(value => !Number.isFinite(Date.parse(value)))
          || (result.status === 'ok' && (
            [result.atr, result.range_14].some(value => typeof value !== 'string' || value.trim() === '' || !Number.isFinite(Number(value)) || Number(value) < 0)
            || [result.atr_pct, result.range_14_pct].some(value => typeof value !== 'number' || !Number.isFinite(value) || value < 0)
          ))) throw new Error('Некорректный ответ расчёта волатильности.')
        if (active) setData(result)
      } catch (reason) {
        if (active) setError(reason instanceof Error && reason.name === 'AbortError'
          ? 'Время ожидания истекло.' : reason instanceof Error ? reason.message : 'Не удалось загрузить волатильность.')
      } finally { clearTimeout(timeout) }
    }, 0)
    return () => { active = false; clearTimeout(start); clearTimeout(timeout); controller.abort() }
  }, [symbol, interval, revision])
  const usable = data?.status === 'ok'
  return <div className="metric">
    <span>Свечи · {interval === '15m' ? '15 минут' : '1 час'}</span>
    <span>ATR(14)</span>
    <strong>{usable ? `${percent(data.atr_pct!)}%` : '—'}</strong>
    {usable && <small>{amount(data.atr!)} USDT</small>}
    {interval === '15m' && data?.score_component && <>
      <small>Волатильность · вклад в Score</small>
      <strong>{usable && data.score_component.status === 'ok'
        && typeof data.score_component.points === 'number' && Number.isFinite(data.score_component.points)
        && data.score_component.points >= 0 && data.score_component.points <= 15 && data.score_component.max_points === 15
        ? `${data.score_component.points.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} / 15` : '—'}</strong>
      <small>{data.score_component.reason}</small>
      <small>Прошлые значения ATR%: {date(data.score_component.baseline_first_at)} — {date(data.score_component.baseline_last_at)}.</small>
    </>}
    <small>Диапазон последних 14 свечей · {interval === '15m' ? '3 ч 30 мин' : '14 часов'}</small>
    <strong>{usable ? `${percent(data.range_14_pct!)}%` : '—'}</strong>
    {usable && <small>{amount(data.range_14!)} USDT · максимум минус минимум</small>}
    {!data && !error && <small role="status">Загрузка…</small>}
    {error && <><small role="alert">{error}</small><button className="refresh" onClick={() => { setData(null); setError(''); setRevision(value => value + 1) }}>Повторить</button></>}
    {data && <>
      <small>Последнее закрытие: {date(data.to_time)}</small>
      <small>Окно диапазона: {date(data.range_from)} — {date(data.range_to)}</small>
      {data.status !== 'ok' && <small>{data.status === 'insufficient_data' ? `Недостаточно данных: отсутствует свечей — ${data.missing_count}.` : 'Некорректные данные свечей.'}</small>}
      {data.warning_count > 0 && <small>Свечей с предупреждениями: {data.warning_count}. Расчёт использует проверенные high, low и close.</small>}
      {data.source_rejected_count > 0 && <small>Отклонено свечей источника: {data.source_rejected_count}.</small>}
    </>}
  </div>
}

export default function VolatilityPanel({ symbol }: { symbol: string }) {
  return <div className="momentum-panel">
    <h3>Волатильность · Bitunix</h3>
    <div className="rsi-grid">
      <VolatilityMetric key={`${symbol}-15m`} symbol={symbol} interval="15m" />
      <VolatilityMetric key={`${symbol}-1h`} symbol={symbol} interval="1h" />
    </div>
    <p className="metric-note">ATR(14) — сглаженный по Уайлдеру диапазон одной свечи с учётом разрыва относительно предыдущего закрытия. История расчёта — 100 завершённых свечей. Проценты ATR и диапазона рассчитаны от последней цены закрытия. Показатели описывают размах колебаний, но не их направление. Обновление — кнопкой «Обновить расчёты».</p>
    <p className="metric-note">Вклад волатильности использует только ATR% на свечах 15 минут. Каждое историческое значение делится на свою цену закрытия; текущее сравнивается с 20 предыдущими. Превышение 19 из 20 даёт 14,25/15 балла. Соседние значения ATR связаны сглаживанием: это относительный ранг, не вероятность события. Высокий ранг возможен и при небольшом повышении ATR. Общий Score ещё не готов.</p>
  </div>
}
