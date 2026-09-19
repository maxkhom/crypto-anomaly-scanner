import { useEffect, useState } from 'react'

type Result = {
  symbol: string; period: string; candle_interval: string; status: string; reason: string | null
  rvol: number | null; current_volume_usdt: string | null; baseline_average_volume_usdt: string | null
  current_from: string; current_to: string; missing_count: number; warning_count: number
}
const volume = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export default function HourRelativeVolume({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 35000)
    const start = setTimeout(async () => {
      try {
        const response = await fetch(`/api/scanner/relative-volume?symbol=${encodeURIComponent(symbol)}&period=1h`, { signal: controller.signal })
        if (!response.ok) throw new Error(`Не удалось получить часовой RVOL (HTTP ${response.status}).`)
        const result: Result = await response.json()
        if (result.symbol !== symbol || result.period !== '1h' || result.candle_interval !== '5m'
          || (result.rvol !== null && !Number.isFinite(result.rvol))
          || ![result.current_from, result.current_to].every((stamp) => Number.isFinite(Date.parse(stamp)))) throw new Error('Неожиданный формат часового RVOL.')
        if (active) setData(result)
      } catch (reason) {
        if (active) setError(reason instanceof Error && reason.name === 'AbortError' ? 'Время ожидания часового RVOL истекло.' : reason instanceof Error ? reason.message : 'Часовой RVOL недоступен.')
      } finally { clearTimeout(timeout) }
    }, 0)
    return () => { active = false; clearTimeout(start); clearTimeout(timeout); controller.abort() }
  }, [symbol, revision])
  return <div className="rvol-panel">
    <div><h3>Relative Volume · 1 час</h3>
      <strong className="rvol-value">{data?.status === 'ok' && data.rvol !== null ? `${data.rvol.toLocaleString('ru-RU', { maximumFractionDigits: 4 })}x` : '—'}</strong>
      <p>По завершённым 5-минутным свечам. Конец окна — на границе пяти минут.</p>
    </div>
    <div className="rvol-details">
      {!data && !error && <p role="status">Получаем историю для часового RVOL…</p>}
      {error && <><p className="rvol-warning" role="alert">{error}</p><button className="refresh" onClick={() => { setError(''); setData(null); setRevision((value) => value + 1) }}>Повторить</button></>}
      {data && <>
        <p>Объём часового окна: <strong>{data.current_volume_usdt === null ? 'нет данных' : `${volume.format(Number(data.current_volume_usdt))} USDT`}</strong></p>
        <p>Среднее предыдущих 20 часовых окон: <strong>{data.baseline_average_volume_usdt === null ? 'нет данных' : `${volume.format(Number(data.baseline_average_volume_usdt))} USDT`}</strong></p>
        <p>Окно: {new Date(data.current_from).toLocaleString('ru-RU')} — {new Date(data.current_to).toLocaleString('ru-RU')} (местное время)</p>
        {data.status !== 'ok' && <p className="rvol-warning">{data.reason === 'missing_candles' ? `Отсутствует 5-минутных свечей: ${data.missing_count}.` : data.reason === 'zero_baseline' ? 'Средний исторический объём равен нулю.' : 'Некорректные данные объёма.'}</p>}
        {data.warning_count > 0 && <p className="rvol-warning">Свечей с предупреждениями: {data.warning_count}. Объёмы прошли проверку.</p>}
      </>}
    </div>
  </div>
}
