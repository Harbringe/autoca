import { describe, expect, it } from 'vitest'
import { parseFy, resolveFy } from './fy'

describe('resolveFy', () => {
  const base = { dataYears: [2024, 2025], current: 2026 }
  it('defaults to the latest year with data, not the current year', () => {
    expect(resolveFy(base)).toEqual({ fy: 2025, explicit: false })
  })
  it('falls back to the current year for a client with no data', () => {
    expect(resolveFy({ dataYears: [], current: 2026 })).toEqual({ fy: 2026, explicit: false })
  })
  it('honours a remembered choice, even an empty year', () => {
    expect(resolveFy({ ...base, remembered: 2026 })).toEqual({ fy: 2026, explicit: true })
  })
  it('lets the URL beat the remembered choice', () => {
    expect(resolveFy({ ...base, remembered: 2025, fromUrl: 2024 })).toEqual({ fy: 2024, explicit: true })
  })
})

describe('parseFy', () => {
  it('accepts a four-digit year as text or number', () => {
    expect(parseFy('2025')).toBe(2025)
    expect(parseFy(2025)).toBe(2025)
  })
  it('rejects rubbish', () => {
    for (const v of ['abc', '25', 1999, 2025.5, undefined, null, '2025-26']) expect(parseFy(v)).toBeUndefined()
  })
})
