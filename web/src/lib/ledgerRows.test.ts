import { describe, expect, it } from 'vitest'
import type { LedgerRow } from '@/api/types'
import { summariseRows, whyNoEntries } from './ledgerRows'

function row(fy: number, posted: boolean, id = Math.random().toString()): LedgerRow {
  return {
    id,
    transaction: id,
    value_date: `${fy}-08-01`,
    financial_year: fy,
    narration: 'UPI/P2M/1/ZERODHA',
    book_narration: '',
    counterparty: 'ZERODHA',
    amount_paise: 10000000,
    amount_display: '₹1,00,000.00',
    is_debit: true,
    is_posted: posted,
    needs_review: false,
    method: 'RULE',
    method_display: 'Rule',
  } as LedgerRow
}

describe('summariseRows', () => {
  it('counts posted and awaiting rows, per year, newest year first', () => {
    const s = summariseRows([row(2025, true), row(2025, false), row(2026, false)])
    expect(s).toMatchObject({ total: 3, posted: 1, awaiting: 2 })
    expect(s.years).toEqual([
      { fy: 2026, posted: 0, awaiting: 1 },
      { fy: 2025, posted: 1, awaiting: 1 },
    ])
  })

  it('is empty for no rows', () => {
    expect(summariseRows([])).toEqual({ total: 0, posted: 0, awaiting: 0, years: [] })
  })
})

describe('whyNoEntries', () => {
  it('says nothing is placed when nothing is', () => {
    expect(whyNoEntries(summariseRows([]), 2026)).toEqual(['No rows are placed in this ledger yet.'])
  })

  it('explains rows that exist but are not posted', () => {
    const reasons = whyNoEntries(summariseRows([row(2026, false), row(2026, false)]), 2026)
    expect(reasons).toEqual(['2 rows placed here have not been posted to the books yet.'])
  })

  it('explains rows that are dated in another year', () => {
    const reasons = whyNoEntries(summariseRows([row(2025, true), row(2025, true)]), 2026)
    expect(reasons).toEqual(['2 rows are dated in FY 2025-26.'])
  })

  it('gives both reasons when both apply, in singular form for one row', () => {
    const reasons = whyNoEntries(summariseRows([row(2025, false)]), 2026)
    expect(reasons).toEqual(['1 row placed here has not been posted to the books yet.', '1 row is dated in FY 2025-26.'])
  })
})
