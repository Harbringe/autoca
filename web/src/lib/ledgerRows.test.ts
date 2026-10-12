import { describe, expect, it } from 'vitest'
import type { LedgerRow } from '@/api/types'
import { summariseRows } from './ledgerRows'

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
