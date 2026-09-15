import { useEffect, useState } from 'react'
import './App.css'

type Ticker = {
  symbol: string
  price: string
  change_24h_pct: number
  volume_24h_usdt: string
}
type Market = {
  exchange: string
  fetched_at: string
  eligible_count: number
  count: number
  unavailable_symbols: string[]
  items: Ticker[]
}
type SortKey = 'symbol' | 'price' | 'change_24h_pct' | 'volume_24h_usdt'

// Reuse an active request when React checks effects twice in development.
let pending: Promise<Market> | null = null
function loadMarket(): Promise<Market> {
  if (pending) return pending
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 25000)
  pending = fetch('/api/market/tickers', { signal: controller.signal })
    .then(async (response) => {
      if (!response.ok) throw new Error(`Не удалось получить котировки (HTTP ${response.status}). Проверь, запущен ли backend, и повтори обновление.`)
      const data: Market = await response.json()
      if (!Array.isArray(data.items) || !Array.isArray(data.unavailable_symbols) || !Number.isFinite(Date.parse(data.fetched_at))) {
        throw new Error('Сервер вернул неожиданный формат данных.')
      }
      return data
    })
    .finally(() => { clearTimeout(timeout); pending = null })
  return pending
}
function errorText(error: unknown) {
  if (error instanceof Error && error.name === 'AbortError') return 'Время ожидания истекло. Попробуй обновить котировки ещё раз.'
  return error instanceof Error ? error.message : 'Не удалось загрузить данные.'
}
const volumeFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const percentFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' })

function App() {
  const [market, setMarket] = useState<Market | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('volume_24h_usdt')
  const [ascending, setAscending] = useState(false)

  useEffect(() => {
    let active = true
    loadMarket().then((data) => { if (active) setMarket(data) })
      .catch((reason: unknown) => { if (active) setError(errorText(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  async function refresh() {
    setLoading(true)
    setError('')
    try { setMarket(await loadMarket()) }
    catch (reason) { setError(errorText(reason)) }
    finally { setLoading(false) }
  }
  function changeSort(key: SortKey) {
    if (sort === key) setAscending(!ascending)
    else { setSort(key); setAscending(key === 'symbol') }
  }
  const rows = (market?.items ?? []).filter((item) => item.symbol.includes(query.trim().toUpperCase()))
    .sort((a, b) => {
      const difference = sort === 'symbol' ? a.symbol.localeCompare(b.symbol) : Number(a[sort]) - Number(b[sort])
      return ascending ? difference : -difference
    })
  const columns: { key: SortKey; label: string }[] = [
    { key: 'symbol', label: 'Монета' }, { key: 'price', label: 'Цена, USDT' },
    { key: 'change_24h_pct', label: 'Изменение 24ч' }, { key: 'volume_24h_usdt', label: 'Объём 24ч, USDT' },
  ]

  return (
    <main className="terminal">
      <header className="header">
        <div><p className="eyebrow">BITUNIX / FUTURES</p><h1>Crypto Anomaly Scanner</h1><p className="subtitle">Обзор рынка · контракты в USDT</p></div>
        <span className="badge">MVP · Рыночные данные</span>
      </header>
      <section className="summary" aria-label="Состояние данных">
        <div><span>Котировки</span><strong>{market?.count ?? '—'}</strong></div>
        <div><span>Последний запрос</span><strong className={error ? 'negative' : market ? 'positive' : ''}>{loading ? 'Загрузка…' : error ? 'Ошибка' : 'Успешно'}</strong></div>
        <div><span>Получено по местному времени</span><strong>{market ? new Date(market.fetched_at).toLocaleTimeString('ru-RU') : '—'}</strong></div>
      </section>
      <section className="panel" aria-label="Скринер">
        <div className="toolbar">
          <div><h2>Рынок</h2><p>Показано {rows.length} из {market?.count ?? 0}</p></div>
          <div className="controls"><label className="search"><span className="sr-only">Поиск монеты</span><input type="search" placeholder="Поиск: BTC, ETH…" value={query} onChange={(event) => setQuery(event.target.value)} /></label><button className="refresh" onClick={refresh} disabled={loading}>{loading ? 'Загрузка…' : 'Обновить'}</button></div>
        </div>
        {error && <p className="notice error" role="alert">{error}{market && ' Ниже — данные предыдущего успешного запроса.'}</p>}
        {!!market?.unavailable_symbols.length && <details className="notice"><summary>Нет корректных котировок: {market.unavailable_symbols.length}</summary><p>{market.unavailable_symbols.join(', ')}</p></details>}
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Таблица котировок, доступна горизонтальная прокрутка" aria-busy={loading}>
          <table><thead><tr>{columns.map((column) => <th key={column.key} scope="col" aria-sort={sort === column.key ? ascending ? 'ascending' : 'descending' : 'none'}><button onClick={() => changeSort(column.key)}>{column.label} <span aria-hidden="true">{sort === column.key ? ascending ? '↑' : '↓' : '↕'}</span></button></th>)}</tr></thead>
            <tbody>{rows.map((item) => <tr key={item.symbol}><td><strong>{item.symbol}</strong><small>Bitunix</small></td><td>{item.price}</td><td className={item.change_24h_pct > 0 ? 'positive' : item.change_24h_pct < 0 ? 'negative' : ''}>{percentFormat.format(item.change_24h_pct)}%</td><td>{volumeFormat.format(Number(item.volume_24h_usdt))}</td></tr>)}</tbody>
          </table>
          {!rows.length && <p className="empty" role="status">{loading ? 'Получаем котировки Bitunix…' : error && !market ? 'Котировки пока недоступны.' : query ? 'По этому запросу ничего не найдено.' : 'Нет доступных котировок.'}</p>}
        </div>
      </section>
      <footer>Обновление вручную · Цена последней сделки · Объём за скользящие 24 часа</footer>
    </main>
  )
}
export default App
