// Where one client stands, worked out from what the API already returns.
//
// Two pure readings, shared by the client list and the profile so they always agree: the next
// step for the books (the words a CA scans down a list for), and which months of a financial year
// a statement covers. No arithmetic on display strings; dates are ISO strings from the server.

import type { BooksStatus, ReviewSummary } from '@/api/types'
import { unsignedThrough } from '@/features/books/state'
import { formatDate, plural } from '@/lib/format'

export type StepTone = 'info' | 'attention' | 'done'

export interface NextStepInfo {
  kind: 'upload' | 'place' | 'post' | 'sign_off' | 'send' | 'done'
  label: string
  tone: StepTone
}

/** The latest statement end date, or null with no statements. */
export function latestEnd(statements: { period_end: string }[] | undefined): string | null {
  return statements?.reduce<string | null>((max, s) => (!max || s.period_end > max ? s.period_end : max), null) ?? null
}

/** What this client's books need next. Same order as the profile's checklist. */
export function nextStep(input: {
  statementCount: number
  latestStatementEnd: string | null
  summary: Pick<ReviewSummary, 'unresolved' | 'pending_approval'> | undefined
  books: Pick<BooksStatus, 'review_pending' | 'signed_off_through'> | undefined
}): NextStepInfo {
  const { statementCount, latestStatementEnd, summary, books } = input
  if (!statementCount) return { kind: 'upload', label: 'Upload a bank statement', tone: 'info' }
  if (summary?.unresolved)
    return { kind: 'place', label: `${plural(summary.unresolved, 'row')} ${summary.unresolved === 1 ? 'needs' : 'need'} a ledger`, tone: 'attention' }
  if (summary?.pending_approval) return { kind: 'post', label: `${plural(summary.pending_approval, 'row')} ready to post`, tone: 'info' }
  if (books?.review_pending) return { kind: 'sign_off', label: 'Sent for review', tone: 'info' }
  if (books && unsignedThrough(books, latestStatementEnd))
    return {
      kind: 'send',
      label: `Send for review${books.signed_off_through ? ` (after ${formatDate(books.signed_off_through)})` : ''}`,
      tone: 'attention',
    }
  return { kind: 'done', label: 'Sealed to date', tone: 'done' }
}

// --- the twelve months of a financial year --------------------------------------------------

export type Coverage = 'full' | 'partial' | 'none'

export interface MonthCover {
  /** First day of the month, ISO. */
  start: string
  /** Short month name, e.g. "Apr". */
  label: string
  coverage: Coverage
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DAY = 86_400_000

const dayNumber = (value: string): number => {
  const [y, m, d] = value.split('-').map(Number)
  return Math.round(Date.UTC(y!, m! - 1, d!) / DAY)
}
const isoDate = (y: number, m0: number, d: number): string => `${y}-${String(m0 + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`

/** For each month April to March of financial year `fy` (named by its starting year): full, partial or no statement cover. */
export function monthCoverage(fy: number, statements: { period_start: string; period_end: string }[]): MonthCover[] {
  // Merge the statements' day ranges so overlapping or adjacent ones are not double counted.
  const spans = statements
    .map((s) => [dayNumber(s.period_start), dayNumber(s.period_end)] as [number, number])
    .filter(([a, b]) => b >= a)
    .sort((x, y) => x[0] - y[0])
  const merged: [number, number][] = []
  for (const [a, b] of spans) {
    const last = merged[merged.length - 1]
    if (last && a <= last[1] + 1) last[1] = Math.max(last[1], b)
    else merged.push([a, b])
  }
  return Array.from({ length: 12 }, (_, i) => {
    const m0 = (3 + i) % 12
    const year = m0 >= 3 ? fy : fy + 1
    const first = dayNumber(isoDate(year, m0, 1))
    const last = dayNumber(isoDate(m0 === 11 ? year + 1 : year, (m0 + 1) % 12, 1)) - 1
    let covered = 0
    for (const [a, b] of merged) covered += Math.max(0, Math.min(b, last) - Math.max(a, first) + 1)
    const total = last - first + 1
    return { start: isoDate(year, m0, 1), label: MONTH_NAMES[m0]!, coverage: covered >= total ? 'full' : covered > 0 ? 'partial' : 'none' }
  })
}

/** "Months with a statement: Apr to Jun. Partly covered: Jul. Missing: Aug to Mar." Runs are joined with "to". */
export function coverageText(months: MonthCover[]): string {
  const describe = (want: Coverage): string => {
    const out: string[] = []
    let run: string[] = []
    const flush = () => {
      if (run.length === 1) out.push(run[0]!)
      else if (run.length === 2) out.push(`${run[0]} and ${run[1]}`)
      else if (run.length > 2) out.push(`${run[0]} to ${run[run.length - 1]}`)
      run = []
    }
    for (const m of months) {
      if (m.coverage === want) run.push(m.label)
      else flush()
    }
    flush()
    return out.join(', ')
  }
  const full = describe('full')
  const partial = describe('partial')
  const none = describe('none')
  const parts = [`Months with a statement: ${full || 'none'}.`]
  if (partial) parts.push(`Partly covered: ${partial}.`)
  if (none) parts.push(`Missing: ${none}.`)
  return parts.join(' ')
}

export interface BooksProgress {
  /** Months of the year that have fully passed, so a statement could cover them. April to March, in order. */
  due: number
  /** Of those, the months a statement covers completely. */
  done: number
  /** Names of the due months no statement touches. */
  missing: string[]
  /** Names of the due months a statement covers only in part. */
  partial: string[]
}

/** The first day of the month after `start` (an ISO first-of-month date). */
const nextMonth = (start: string): string => {
  const y = Number(start.slice(0, 4))
  const m = Number(start.slice(5, 7))
  return m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`
}

/**
 * How far the statements have got, in whole months. A month is due once it has fully passed (`today`
 * is an ISO date), so the month in progress never counts against anyone. Integers only.
 */
export function booksProgress(months: MonthCover[], today: string): BooksProgress {
  const due = months.filter((m) => nextMonth(m.start) <= today)
  return {
    due: due.length,
    done: due.filter((m) => m.coverage === 'full').length,
    missing: due.filter((m) => m.coverage === 'none').map((m) => m.label),
    partial: due.filter((m) => m.coverage === 'partial').map((m) => m.label),
  }
}
