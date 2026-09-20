import { useEffect, useState } from 'react'

type Funding = {
  exchange: string; symbol: string; unit: string; funding_rate_pct: string
  interval_hours: number; next_funding_time: string; fetched_at: string
  min_funding_rate_pct: string; max_funding_rate_pct: string
  payment_direction: string; status: string
  score_part?: { status: string; points: number | null; max_points: number; reason: string }
}
const format = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 6, signDisplay: 'exceptZero' })
const directions: Record<string, string> = {
  shorts_pay_longs: 'Шорты платят лонгам', longs_pay_shorts: 'Лонги платят шортам', none: 'Ставка равна нулю',
}

export default function FundingRate({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Funding | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    const start = setTimeout(async () => {
      try {
        const response = await fetch(`/api/scanner/funding?symbol=${encodeURIComponent(symbol)}`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error(`Funding Bitunix недоступен (HTTP ${response.status}).`)
        const result: Funding = await response.json()
        if (result.exchange !== 'bitunix' || result.symbol !== symbol || result.unit !== 'percent'
          || !['ok', 'settlement_time_passed'].includes(result.status)
          || !directions[result.payment_direction] || !Number.isInteger(result.interval_hours) || result.interval_hours <= 0
          || ![result.funding_rate_pct, result.min_funding_rate_pct, result.max_funding_rate_pct].every((value) => typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)))
          || ![result.next_funding_time, result.fetched_at].every((value) => Number.isFinite(Date.parse(value)))) {
          throw new Error('Некорректный ответ Funding Bitunix.')
        }
        if (active) { setData(result); setNow(Date.now()) }
      } catch (reason) {
        if (active) setError(reason instanceof Error && reason.name === 'AbortError' ? 'Время ожидания Funding Bitunix истекло.' : reason instanceof Error ? reason.message : 'Funding недоступен.')
      } finally { clearTimeout(timeout) }
    }, 0)
    return () => { active = false; clearTimeout(start); clearTimeout(timeout); controller.abort() }
  }, [symbol, revision])
  const expired = data && (data.status !== 'ok' || Date.parse(data.next_funding_time) <= now)
  return <div className="rvol-panel">
    <div><h3>Funding Rate · Bitunix</h3>
      <strong className="rvol-value">{data ? `${format.format(Number(data.funding_rate_pct))}%` : '—'}</strong>
      {data && <p>За период {data.interval_hours} ч · {directions[data.payment_direction]}</p>}
      {data?.score_part && <>
        <h3>Funding · вклад в Extras</h3>
        <strong className="rvol-value">{!expired && data.score_part.status === 'ok'
          && typeof data.score_part.points === 'number' && Number.isFinite(data.score_part.points)
          && data.score_part.points >= 0 && data.score_part.points <= 5 && data.score_part.max_points === 5
          ? `${data.score_part.points.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} / 5` : '—'}</strong>
        <p>{data.score_part.reason}</p>
      </>}
    </div>
    <div className="rvol-details">
      {!data && !error && <p role="status">Получаем ставку финансирования…</p>}
      {error && <p className="rvol-warning" role="alert">{error}</p>}
      {data && <>
        <p>{expired ? 'Указанное время начисления' : 'Следующее начисление'}: <strong>{new Date(data.next_funding_time).toLocaleString('ru-RU')}</strong> (местное время)</p>
        <p>Пределы ставки: {format.format(Number(data.min_funding_rate_pct))}% / {format.format(Number(data.max_funding_rate_pct))}%</p>
        <p>Получено: {new Date(data.fetched_at).toLocaleString('ru-RU')}</p>
        {expired && <p className="rvol-warning">Время начисления прошло. Показана ранее полученная ставка — требуется обновление.</p>}
        <p>Ставка может измениться до начисления. Funding — дополнительный показатель, а не самостоятельный сигнал на вход.</p>
        {data.score_part && <p>Предварительное правило: половина соответствующего предела ставки даёт 2,5/5 балла. Используется предел для текущего периода начисления. Эта оценка не сравнивает стоимость Funding за одинаковое число часов и может меняться при изменении пределов биржи.</p>}
      </>}
      {(error || expired) && <button className="refresh" onClick={() => { setData(null); setError(''); setRevision((value) => value + 1) }}>Обновить funding</button>}
    </div>
  </div>
}
