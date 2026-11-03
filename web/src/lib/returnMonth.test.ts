import { describe, expect, it } from 'vitest'
import { defaultReturnMonth, previousMonth } from './returnMonth'

describe('defaultReturnMonth', () => {
  it('is the month just ended when it falls inside the year', () => {
    expect(defaultReturnMonth(2026, new Date(2026, 10, 3))).toBe('2026-10')
    expect(defaultReturnMonth(2025, new Date(2026, 0, 15))).toBe('2025-12')
  })

  it('is April for a year that has not started and March for one that has ended', () => {
    expect(defaultReturnMonth(2027, new Date(2026, 10, 3))).toBe('2027-04')
    expect(defaultReturnMonth(2024, new Date(2026, 10, 3))).toBe('2025-03')
  })

  it('is April when April has only just begun', () => {
    expect(defaultReturnMonth(2026, new Date(2026, 3, 5))).toBe('2026-04')
  })
})

describe('previousMonth', () => {
  it('goes back into the earlier year in January', () => {
    expect(previousMonth(new Date(2027, 0, 9))).toEqual({ year: 2026, month: 12 })
    expect(previousMonth(new Date(2026, 10, 3))).toEqual({ year: 2026, month: 10 })
  })
})
