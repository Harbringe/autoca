import { describe, expect, it } from 'vitest'
import { ageSegments, ageSegmentsFromList, overNinetySegments, sumSegments } from './ageing'

describe('ageing segments', () => {
  it('always gives the four buckets in order, fresh to stale', () => {
    const s = ageSegments({ 'Over 90': 500_00, '0-30': 100_00 })
    expect(s.map((x) => x.key)).toEqual(['0-30', '31-60', '61-90', 'Over 90'])
    expect(s.map((x) => x.value)).toEqual([100_00, 0, 0, 500_00])
    expect(s[3]!.tone).toBe('bad')
  })
  it('keeps the exact amount for the hidden table and shortens the label', () => {
    const [first] = ageSegments({ '0-30': 12_345_678_90 })
    expect(first!.fullLabel).toBe('₹1,23,45,678.90')
    expect(first!.valueLabel).toBe('₹1.23 Cr')
  })
  it('reads the portfolio list shape, ignores unknown buckets and never goes negative', () => {
    const s = ageSegmentsFromList([
      { bucket: '31-60', amount_paise: 2_000_00 },
      { bucket: 'Later', amount_paise: 9 },
      { bucket: '0-30', amount_paise: -5 },
    ])
    expect(s.map((x) => x.value)).toEqual([0, 2_000_00, 0, 0])
  })
  it('splits a side that only knows its over-90 amount, and never lets the part exceed the whole', () => {
    expect(overNinetySegments(1_000_00, 300_00).map((x) => x.value)).toEqual([700_00, 300_00])
    expect(overNinetySegments(100_00, 900_00).map((x) => x.value)).toEqual([0, 100_00])
    expect(sumSegments(overNinetySegments(0, 0))).toBe(0)
  })
})
