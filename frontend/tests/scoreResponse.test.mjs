import test from 'node:test'
import assert from 'node:assert/strict'
import { parseScore, scoreWeights } from '../src/scoreResponse.ts'

function fixture() {
  return {
    symbol: 'BTCUSDT', as_of: '2026-09-20T08:03:42+00:00', model_version: 'cross_market_score_v1',
    status: 'ok', score: 0, coverage_pct: 100, missing_components: [],
    components: Object.fromEntries(Object.entries(scoreWeights).map(([key, weight]) => [key, {
      label: key, status: 'ok', normalized_score: 0, points: 0, max_points: weight, reason: 'Example', details: {},
    }])),
  }
}

test('valid zero is a complete score, not missing data', () => {
  assert.equal(parseScore(fixture(), 'BTCUSDT').score, 0)
})
test('missing acceleration preserves 75% coverage without a total', () => {
  const data = fixture()
  Object.assign(data, { status: 'incomplete', score: null, coverage_pct: 75, missing_components: ['price_acceleration'] })
  Object.assign(data.components.price_acceleration, { status: 'insufficient_data', normalized_score: null, points: null })
  assert.equal(parseScore(data, 'BTCUSDT').score, null)
  assert.equal(parseScore(data, 'BTCUSDT').components.relative_volume.points, 0)
  data.score = 0
  assert.throws(() => parseScore(data, 'BTCUSDT'))
})
test('wrong symbol, nonfinite values, incorrect weights and inconsistent totals are rejected', () => {
  assert.throws(() => parseScore(fixture(), 'ETHUSDT'))
  for (const mutate of [
    data => { data.score = NaN },
    data => { data.score = 30 },
    data => { data.coverage_pct = 75 },
    data => { data.components.extras.max_points = 25 },
    data => { data.components.extras.points = 11 },
    data => { data.components.extras.normalized_score = Infinity },
    data => { delete data.components.open_interest },
    data => { data.components.extras.details = null },
  ]) {
    const data = fixture()
    mutate(data)
    assert.throws(() => parseScore(data, 'BTCUSDT'))
  }
})
test('complete weighted contributions are preserved', () => {
  const data = fixture()
  for (const component of Object.values(data.components)) {
    component.normalized_score = 50
    component.points = component.max_points / 2
  }
  data.score = 50
  assert.equal(parseScore(data, 'BTCUSDT').score, 50)
})
test('unavailable response requires all contributions to be missing', () => {
  const data = fixture()
  Object.assign(data, { status: 'unavailable', score: null, coverage_pct: 0, missing_components: Object.keys(scoreWeights) })
  for (const component of Object.values(data.components)) {
    Object.assign(component, { status: 'unavailable', points: null, normalized_score: null })
  }
  assert.equal(parseScore(data, 'BTCUSDT').coverage_pct, 0)
})
