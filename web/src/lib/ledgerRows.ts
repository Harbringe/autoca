// A ledger's "rows placed" counts every row put in it, in any year, posted or not. The books hold
// only what has been posted, one financial year at a time. This helper counts the rows per year
// and how many of them are posted.

import type { LedgerRow } from '@/api/types'

export interface YearCount {
  fy: number
  posted: number
  awaiting: number
}

export interface RowSummary {
  total: number
  posted: number
  awaiting: number
  /** Years that have rows, newest first. */
  years: YearCount[]
}

export function summariseRows(rows: LedgerRow[]): RowSummary {
  const byYear = new Map<number, YearCount>()
  let posted = 0
  for (const row of rows) {
    const year = byYear.get(row.financial_year) ?? { fy: row.financial_year, posted: 0, awaiting: 0 }
    if (row.is_posted) {
      year.posted += 1
      posted += 1
    } else {
      year.awaiting += 1
    }
    byYear.set(row.financial_year, year)
  }
  return {
    total: rows.length,
    posted,
    awaiting: rows.length - posted,
    years: [...byYear.values()].sort((a, b) => b.fy - a.fy),
  }
}
