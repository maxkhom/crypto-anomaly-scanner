import { useEffect, useState } from 'react'

type Event = {
  id: number; symbol: string; interval_start: string; interval_end: string
  detected_at: string; start_price: string; end_price: string
  change_pct: number; percentile: number; direction: 'up' | 'down'
}
type History = { total: number; count: number; items: Event[] }
const percent = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4, signDisplay: 'exceptZero' })

function validHistory(data: History) {
  return data && Number.isInteger(data.total) && data.total >= 0
    && Array.isArray(data.items) && data.count === data.items.length && data.total >= data.count
    && data.items.every((item) => item && Number.isInteger(item.id) && typeof item.symbol === 'string'
      && ['up', 'down'].includes(item.direction)
      && [item.interval_start, item.interval_end, item.detected_at].every((value) => Number.isFinite(Date.parse(value)))
      && [item.start_price, item.end_price].every((value) => typeof value === 'string' && Number.isFinite(Number(value)) && Number(value) > 0)
      && Number.isFinite(item.change_pct) && Number.isFinite(item.percentile) && item.percentile >= 0 && item.percentile <= 100)
}

export default function AlertHistory() {
  const [history, setHistory] = useState<History | null>(null)
  const [error, setError] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let controller: AbortController | undefined
    async function update() {
      controller = new AbortController()
      const timeout = setTimeout(() => controller?.abort(), 5000)
      try {
        const response = await fetch('/api/scanner/events?limit=50', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('History unavailable')
        const data: History = await response.json()
        if (!validHistory(data)) throw new Error('Invalid history')
        if (active) { setHistory(data); setUpdatedAt(new Date()); setError(false) }
      } catch {
        if (active) setError(true)
      } finally {
        clearTimeout(timeout)
        if (active) timer = setTimeout(update, 5000)
      }
    }
    timer = setTimeout(update, 0)
    return () => { active = false; clearTimeout(timer); controller?.abort() }
  }, [])
  return <section className="panel price-panel" aria-label="История аномалий">
    <div className="toolbar"><div><h2>История аномалий</h2>
      <p>{history ? `Последние ${history.count} из ${history.total} событий` : 'Загрузка истории…'} · обновление каждые 5 секунд</p>
      {updatedAt && <p>Последний успешный запрос: {updatedAt.toLocaleTimeString('ru-RU')}</p>}
    </div></div>
    {error && <p className="notice error" role="alert">История временно недоступна. Повторяем запрос…{history && ' Ниже сохранён результат последнего успешного запроса.'}</p>}
    {history && history.items.length > 0 && <div className="table-scroll" tabIndex={0} role="region" aria-label="История событий, доступна горизонтальная прокрутка">
      <table><thead><tr><th>Монета</th><th>Событие</th><th>Конец интервала</th><th>Цена в начале</th><th>Цена в конце</th><th>Движение · 10 с</th><th>Необычность</th></tr></thead>
        <tbody>{history.items.map((item) => <tr key={item.id}>
          <td><strong>{item.symbol}</strong><small>Bitunix</small></td>
          <td className={item.direction === 'up' ? 'positive' : 'negative'}>{item.direction === 'up' ? 'Аномальный рост' : 'Аномальное падение'}</td>
          <td title={`Обнаружено: ${new Date(item.detected_at).toLocaleString('ru-RU')}`}>{new Date(item.interval_end).toLocaleString('ru-RU')}</td>
          <td>{item.start_price}</td><td>{item.end_price}</td>
          <td className={item.change_pct > 0 ? 'positive' : 'negative'}>{percent.format(item.change_pct)}%</td>
          <td>{item.percentile.toLocaleString('ru-RU')}%</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {history?.total === 0 && !error && <p className="empty">Событий пока нет. Запись начнётся, когда движение пройдёт оба порога и будет доступна полная история сравнения.</p>}
    <p className="metric-note">Текущее правило v2: необычность ≥95% и движение по модулю ≥0,1% за 10 секунд. База — 180 последних валидных returns в пределах 45 минут перед оцениваемым интервалом; пропуски не заполняются. Старые события v1 рассчитаны по прежнему окну 30 минут. Фильтры таблицы не влияют на запись событий. Цены указаны в USDT, время — местное. Это наблюдения, а не торговые рекомендации.</p>
  </section>
}
