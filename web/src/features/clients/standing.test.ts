import { describe, expect, it } from 'vitest'
import { coverageText, latestEnd, monthCoverage, nextStep } from './standing'

const summary = (unresolved: number, pending_approval: number) => ({ unresolved, pending_approval })
const books = (review_pending: boolean, signed_off_through: string | null) => ({ review_pending, signed_off_through })

describe('nextStep', () => {
  it('asks for a statement first', () => {
    expect(nextStep({ statementCount: 0, latestStatementEnd: null, summary: undefined, books: undefined }).kind).toBe('upload')
  })
  it('follows the checklist order: place, post, sign-off, send, done', () => {
    const base = { statementCount: 1, latestStatementEnd: '2025-04-30' }
    expect(nextStep({ ...base, summary: summary(3, 5), books: books(false, null) })).toMatchObject({ kind: 'place', label: '3 rows need a ledger' })
    expect(nextStep({ ...base, summary: summary(1, 0), books: books(false, null) }).label).toBe('1 row needs a ledger')
    expect(nextStep({ ...base, summary: summary(0, 16), books: books(false, null) })).toMatchObject({ kind: 'post', label: '16 rows ready to post' })
    expect(nextStep({ ...base, summary: summary(0, 0), books: books(true, null) }).kind).toBe('sign_off')
    expect(nextStep({ ...base, summary: summary(0, 0), books: books(false, '2025-03-31') })).toMatchObject({
      kind: 'send',
      label: 'Send for review (after 31-03-2025)',
    })
    expect(nextStep({ ...base, summary: summary(0, 0), books: books(false, '2025-04-30') }).kind).toBe('done')
  })
})

describe('latestEnd', () => {
  it('is the largest period end, or null', () => {
    expect(latestEnd([{ period_end: '2025-04-30' }, { period_end: '2025-06-30' }, { period_end: '2025-05-31' }])).toBe('2025-06-30')
    expect(latestEnd([])).toBeNull()
    expect(latestEnd(undefined)).toBeNull()
  })
})

describe('monthCoverage', () => {
  it('runs April to March of the named year', () => {
    const months = monthCoverage(2025, [])
    expect(months.map((m) => m.label).join(' ')).toBe('Apr May Jun Jul Aug Sep Oct Nov Dec Jan Feb Mar')
    expect(months[0]!.start).toBe('2025-04-01')
    expect(months[11]!.start).toBe('2026-03-01')
    expect(months.every((m) => m.coverage === 'none')).toBe(true)
  })
  it('marks full and partial months, across statements that meet or overlap', () => {
    const months = monthCoverage(2025, [
      { period_start: '2025-04-01', period_end: '2025-05-31' },
      { period_start: '2025-06-01', period_end: '2025-06-20' },
      { period_start: '2025-06-15', period_end: '2025-06-25' },
    ])
    expect(months.slice(0, 4).map((m) => m.coverage)).toEqual(['full', 'full', 'partial', 'none'])
  })
  it('handles a statement that straddles a month and the leap-year February', () => {
    const months = monthCoverage(2023, [{ period_start: '2024-01-15', period_end: '2024-02-29' }])
    expect(months[9]!.coverage).toBe('partial') // Jan
    expect(months[10]!.coverage).toBe('full') // Feb 2024 has 29 days
  })
  it('gives a text alternative that names runs', () => {
    const months = monthCoverage(2025, [{ period_start: '2025-04-01', period_end: '2025-06-30' }])
    expect(coverageText(months)).toBe('Months with a statement: Apr to Jun. Missing: Jul to Mar.')
    const partial = monthCoverage(2025, [{ period_start: '2025-04-01', period_end: '2025-07-10' }])
    expect(coverageText(partial)).toBe('Months with a statement: Apr to Jun. Partly covered: Jul. Missing: Aug to Mar.')
    expect(coverageText(monthCoverage(2025, []))).toBe('Months with a statement: none. Missing: Apr to Mar.')
  })
})
