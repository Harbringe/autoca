import { describe, expect, it } from 'vitest'
import { monthsSummary } from './MonthBars'

const m = (month: string, income_paise: number, expense_paise: number) => ({ month, income_paise, expense_paise })

describe('monthsSummary', () => {
  it('says nothing is posted for an empty year', () => {
    expect(monthsSummary([m('2026-04', 0, 0)])).toBe('Nothing has been posted in this financial year yet.')
  })
  it('names the one month when only one has entries, instead of counting "0 of 1"', () => {
    expect(monthsSummary([m('2026-04', 0, 0), m('2026-08', 0, 500_00)])).toBe('Only August 2026 has entries so far.')
  })
  it('counts months where income beat expense when there are several', () => {
    expect(monthsSummary([m('2026-04', 900, 100), m('2026-05', 100, 900), m('2026-06', 500, 100)])).toBe('Income was higher than expense in 2 of the 3 months with entries.')
  })
})
