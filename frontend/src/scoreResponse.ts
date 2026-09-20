export const scoreWeights = { price_acceleration: 25, relative_volume: 25, open_interest: 25, volatility: 15, extras: 10 } as const
export type ScoreKey = keyof typeof scoreWeights
export type ScoreComponent = {
  label: string; status: string; normalized_score: number | null
  points: number | null; max_points: number; reason: string; details: Record<string, unknown>
}
export type ScoreResponse = {
  symbol: string; as_of: string; model_version: string; status: string
  score: number | null; coverage_pct: number; missing_components: ScoreKey[]
  components: Record<ScoreKey, ScoreComponent>
}
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const bounded = (value: unknown, max: number): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max

export function parseScore(value: unknown, symbol: string): ScoreResponse {
  const fail = () => { throw new Error('Некорректный ответ общего Anomaly Score.') }
  if (!record(value) || value.symbol !== symbol || typeof value.as_of !== 'string' || !Number.isFinite(Date.parse(value.as_of))
    || typeof value.model_version !== 'string' || !['ok', 'incomplete', 'unavailable', 'invalid_data'].includes(String(value.status))
    || !bounded(value.coverage_pct, 100) || !record(value.components) || !Array.isArray(value.missing_components)) return fail()
  let coverage = 0
  let total = 0
  const missing: string[] = []
  for (const [key, weight] of Object.entries(scoreWeights)) {
    const component = value.components[key]
    if (!record(component) || typeof component.label !== 'string' || typeof component.reason !== 'string'
      || !['ok', 'unavailable', 'insufficient_data', 'warming_up', 'stale', 'invalid_data'].includes(String(component.status))
      || component.max_points !== weight || !record(component.details)) return fail()
    if (component.status === 'ok') {
      if (!bounded(component.points, weight) || !bounded(component.normalized_score, 100)) return fail()
      coverage += weight
      total += component.points
    } else {
      if (component.points !== null || component.normalized_score !== null) return fail()
      missing.push(key)
    }
  }
  const suppliedMissing = value.missing_components
  if (coverage !== value.coverage_pct || missing.length !== suppliedMissing.length
    || !missing.every(key => suppliedMissing.includes(key))) return fail()
  if (missing.length === 0) {
    if (value.status !== 'ok' || !bounded(value.score, 100) || Math.abs(value.score - total) > 0.011) return fail()
  } else if (value.status === 'ok' || value.score !== null) return fail()
  return value as ScoreResponse
}
