// A ledger's "rows placed" counts every row put in it, in any year, posted or not. The books hold
// only what has been posted, one financial year at a time. These two helpers say how the two
// numbers relate, so a ledger that shows rows and no entries can say why.

import type { LedgerRow } from '@/api/types'
import { fyLabel, plural } from '@/lib/format'

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

/** Why a ledger has no posted entries in `fy`, in sentences a person can act on. */
export function whyNoEntries(summary: RowSummary, fy: number): string[] {
  if (summary.total === 0) return ['No rows are placed in this ledger yet.']
  const elsewhere = summary.years.filter((y) => y.fy !== fy)
  const inOtherYears = elsewhere.reduce((n, y) => n + y.posted + y.awaiting, 0)
  const reasons: string[] = []
  if (summary.awaiting > 0) {
    reasons.push(`${plural(summary.awaiting, 'row')} placed here ${summary.awaiting === 1 ? 'has' : 'have'} not been posted to the books yet.`)
  }
  if (inOtherYears > 0) {
    reasons.push(`${plural(inOtherYears, 'row')} ${inOtherYears === 1 ? 'is' : 'are'} dated in ${elsewhere.map((y) => `FY ${fyLabel(y.fy)}`).join(', ')}.`)
  }
  return reasons
}
