import { describe, expect, it } from 'vitest'
import { pct, percentages } from './pct'

describe('percentages', () => {
  it('sums to 100 when thirds would round to 99', () => {
    const out = percentages([1, 1, 1])
    expect(out.reduce((a, b) => a + b, 0)).toBe(100)
    expect(out).toEqual([34, 33, 33])
  })
  it('sums to 100 when halves would round to 101', () => {
    expect(percentages([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]).reduce((a, b) => a + b, 0)).toBe(100)
    expect(percentages([9, 11, 14, 7, 0, 0]).reduce((a, b) => a + b, 0)).toBe(100)
  })
  it('is all zeros for no work, and keeps zero rows at zero', () => {
    expect(percentages([0, 0, 0])).toEqual([0, 0, 0])
    expect(percentages([])).toEqual([])
    expect(percentages([5, 0])).toEqual([100, 0])
  })
})

describe('pct', () => {
  it('rounds to nearest and guards the empty case', () => {
    expect(pct(7, 12)).toBe(58)
    expect(pct(3, 0)).toBe(0)
    expect(pct(12, 12)).toBe(100)
  })
})
