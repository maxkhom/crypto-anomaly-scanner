import { useEffect, useRef, useState } from 'react'
import { parseScore, scoreWeights } from './scoreResponse'
import type { ScoreKey, ScoreResponse } from './scoreResponse'

const format = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
const statuses: Record<string, string> = {
  ok: 'Готово', incomplete: 'Недостаточно данных', unavailable: 'Данные недоступны',
  insufficient_data: 'Недостаточно данных', warming_up: 'Накопление истории', stale: 'Данные устарели', invalid_data: 'Ошибка данных',
}
function date(value: unknown) {
  return typeof value === 'string' && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ru-RU') : null
}

export default function AnomalyScorePanel({ symbol }: { symbol: string }) {
  const [data, setData] = useState<ScoreResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => { request.current?.abort(); request.current = null }, [])

  async function refresh() {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    setData(null)
    setError('')
    setLoading(true)
    const timeout = setTimeout(() => controller.abort(), 45000)
    try {
      const response = await fetch(`/api/scanner/anomaly-score?symbol=${encodeURIComponent(symbol)}`, { signal: controller.signal, cache: 'no-store' })
      if (!response.ok) throw new Error(`Не удалось получить Score (HTTP ${response.status}).`)
      const result = parseScore(await response.json(), symbol)
      if (request.current === controller) setData(result)
    } catch (reason) {
      if (request.current === controller) setError(reason instanceof Error && reason.name === 'AbortError'
        ? 'Время ожидания Score истекло. Повторите расчёт.' : reason instanceof Error ? reason.message : 'Score недоступен.')
    } finally {
      clearTimeout(timeout)
      if (request.current === controller) { request.current = null; setLoading(false) }
    }
  }

  return <section className="momentum-panel score-panel" aria-label={`Anomaly Score ${symbol}`} aria-busy={loading}>
    <div className="toolbar">
      <div><h3>Anomaly Score · {symbol}</h3><p>Экспериментальная оценка · Bitunix + OI Bybit</p></div>
      <button className="refresh" disabled={loading} onClick={refresh}>{loading ? 'Расчёт…' : data || error ? 'Обновить Score' : 'Рассчитать Score'}</button>
    </div>
    {!data && !error && <p className="metric-note" role="status">{loading ? 'Получаем данные и проверяем пять компонентов…' : 'Нажмите «Рассчитать Score», чтобы получить общий результат для выбранной монеты.'}</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
    {data && <>
      <div className="score-summary" aria-live="polite">
        <div><span>Общий Score</span><strong>{data.score === null ? '—' : `${format(data.score)} / 100`}</strong><p>{statuses[data.status]}</p></div>
        <div><span>Доступность компонентов по весам</span><strong>{format(data.coverage_pct)}%</strong><p>Это полнота данных, не вероятность успеха.</p></div>
      </div>
      <p className="metric-note">Снимок на {date(data.as_of)} (местное время). Автоматически не обновляется. Компоненты используют разные периоды и могут отличаться от отдельно загруженных показателей ниже.</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Вклады в Anomaly Score, доступна горизонтальная прокрутка">
        <table className="score-table"><thead><tr><th>Компонент</th><th>Баллы</th><th>Данные</th><th>Объяснение</th></tr></thead>
          <tbody>{(Object.keys(scoreWeights) as ScoreKey[]).map(key => {
            const item = data.components[key]
            const details = item.details
            const observed = date(details.observed_at)
            return <tr key={key}>
              <td>{item.label}<small>{details.exchange === 'bybit' ? 'Bybit' : 'Bitunix'}</small></td>
              <td>{item.points === null ? `— / ${item.max_points}` : `${format(item.points)} / ${item.max_points}`}</td>
              <td>{statuses[item.status]}{observed && <small>{observed}</small>}
                {typeof details.valid_samples === 'number' && typeof details.required_samples === 'number' && <small>История {details.valid_samples}/{details.required_samples}</small>}
                {date(details.funding_observed_at) && <small>Funding: {date(details.funding_observed_at)}</small>}
                {date(details.rsi_observed_at) && <small>RSI: {date(details.rsi_observed_at)}</small>}
              </td>
              <td>{item.reason}
                {typeof details.warning_count === 'number' && details.warning_count > 0 && <small>Свечей с предупреждениями: {details.warning_count}.</small>}
                {details.source_quality === 'partial' && <small>Источник вернул частично пригодную историю.</small>}
              </td>
            </tr>
          })}</tbody>
        </table>
      </div>
      {data.score === null && <p className="metric-note">Итог недоступен, пока не готовы все пять компонентов. Пропуски не заменяются нулями, веса не перераспределяются.</p>}
      <p className="metric-note">Score описывает необычность по правилам модели, а не вероятность успешной сделки. OI относится к Bybit; цены и объёмы — к Bitunix. Модель: {data.model_version}.</p>
    </>}
  </section>
}
