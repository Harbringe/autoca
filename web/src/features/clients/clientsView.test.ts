import { describe, expect, it } from 'vitest'
import { barPercent, filterCounts, initials } from './clientsView'

describe('initials', () => {
  it('takes the first letter of the first two words, capitalised', () => {
    expect(initials('Gajanan Cloth Center')).toBe('GC')
    expect(initials('shri narayan trading co.')).toBe('SN')
  })
  it('handles one word and empty names', () => {
    expect(initials('Laxmi')).toBe('L')
    expect(initials('   ')).toBe('?')
  })
})

describe('barPercent', () => {
  it('scales to the busiest client', () => {
    expect(barPercent(783, 783)).toBe(100)
    expect(barPercent(286, 783)).toBe(37)
  })
  it('keeps a small non-zero count visible and zero empty', () => {
    expect(barPercent(1, 783)).toBe(4)
    expect(barPercent(0, 783)).toBe(0)
    expect(barPercent(5, 0)).toBe(0)
  })
})

describe('filterCounts', () => {
  it('counts what each pill would show', () => {
    const rows = [
      { unresolved: 783, ready: 0, mine: true, assigned: true },
      { unresolved: 6, ready: 6, mine: true, assigned: true },
      { unresolved: 0, ready: 70, mine: false, assigned: true },
      { unresolved: 0, ready: 0, mine: false, assigned: false },
    ]
    expect(filterCounts(rows)).toEqual({ all: 4, mine: 2, unresolved: 2, ready: 2, unassigned: 1 })
  })
})
