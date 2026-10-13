import { describe, expect, it } from 'vitest'
import type { Classification, Statement } from '@/api/types'
import { askedOf, resolveSelection, scopedCounts, selectionSummary, statementChoices, toggled, waitingStatements } from './statementChoices'

const statement = (id: string, label: string, start: string, end: string, count = 0) =>
  ({ id, bank_account_label: label, period_start: start, period_end: end, transaction_count: count }) as unknown as Statement
const row = (n: number, statementId: string, over: Partial<Classification> = {}) => ({ id: `r${n}`, transaction: { statement: statementId }, ...over }) as unknown as Classification

const STATEMENTS = [
  statement('s2', 'Icici Bank A/c 7921', '2025-04-03', '2026-03-31', 10),
  statement('s1', 'Generic Bank A/c 5335', '2025-01-01', '2025-03-31', 6),
  statement('s3', 'Empty one', '2024-01-01', '2024-03-31', 4),
]

describe('statements to review', () => {
  it('lists the statements that have rows waiting, oldest first, with how many', () => {
    const choices = statementChoices(STATEMENTS, [row(1, 's2'), row(2, 's2'), row(3, 's1')])
    expect(choices.map((c) => [c.id, c.count])).toEqual([['s1', 1], ['s2', 2]])
    expect(choices[0]).toMatchObject({ label: 'Generic Bank A/c 5335', period: '01-01-2025 to 31-03-2025' })
  })

  it('leaves out a statement with nothing waiting, and rows of a statement that is not known', () => {
    expect(statementChoices(STATEMENTS, [row(1, 'nowhere')])).toEqual([])
  })

  it('counts a statement as waiting when either queue has rows of it', () => {
    const w = waitingStatements(STATEMENTS, [row(1, 's1')], [row(2, 's2'), row(3, 's1')])
    expect(w.map((c) => [c.id, c.count])).toEqual([['s1', 2], ['s2', 1]])
  })
})

describe('which statements are chosen', () => {
  const two = waitingStatements(STATEMENTS, [row(1, 's2')], [row(2, 's1')])

  it('starts with the oldest statement that has work when there is more than one, and with all of them when there is one', () => {
    expect(resolveSelection(undefined, two, STATEMENTS)).toEqual(['s1'])
    expect(resolveSelection(undefined, waitingStatements(STATEMENTS, [row(1, 's2')], []), STATEMENTS)).toBeNull()
    expect(resolveSelection(undefined, [], STATEMENTS)).toBeNull()
  })

  it('takes one, several or all from the address, and ignores ids that are not this client’s statements', () => {
    expect(resolveSelection('s2', two, STATEMENTS)).toEqual(['s2'])
    expect(resolveSelection('s2,s1', two, STATEMENTS)).toEqual(['s2', 's1'])
    expect(resolveSelection('all', two, STATEMENTS)).toBeNull()
    expect(resolveSelection('gone', two, STATEMENTS)).toEqual(['s1'])
    expect(resolveSelection('s1,gone,s1', two, STATEMENTS)).toEqual(['s1'])
  })

  it('writes the choice back to the address', () => {
    expect(askedOf(null)).toBe('all')
    expect(askedOf(['s1', 's2'])).toBe('s1,s2')
  })

  it('ticks and unticks, keeps at least one, and calls ticking every one "all"', () => {
    expect(toggled(['s1'], 's2', two)).toBe('all')
    const three = waitingStatements(STATEMENTS, [row(1, 's1'), row(2, 's2')], [row(3, 's3')])
    expect(three.map((c) => c.id)).toEqual(['s3', 's1', 's2'])
    expect(toggled(['s3'], 's2', three)).toBe('s3,s2')
    expect(toggled(['s3', 's2'], 's3', three)).toBe('s2')
    expect(toggled(['s2'], 's2', three)).toBe('s2')
    expect(toggled(null, 's1', three)).toBe('s3,s2')
  })

  it('describes the choice', () => {
    expect(selectionSummary(['s1'], two)).toBe('01-01-2025 to 31-03-2025')
    expect(selectionSummary(['s1', 's2'], two)).toBe('2 statements chosen')
    expect(selectionSummary(null, two)).toContain('2 statements')
  })
})

describe('the numbers for the statements chosen', () => {
  const needs = [row(1, 's1'), row(2, 's2'), row(3, 's2', { on_party_account: true })]
  const ready = [row(4, 's1'), row(5, 's3')]

  it('is nothing special when all are chosen: the client’s own totals apply', () => {
    expect(scopedCounts(null, needs, ready, STATEMENTS)).toBeNull()
  })

  it('counts each stage, the sum, those to settle by hand, and what is already posted, for the chosen ones only', () => {
    expect(scopedCounts(['s1'], needs, ready, STATEMENTS)).toEqual({ unresolved: 1, pending_approval: 1, all: 2, posted: 4, settling: 0 })
    expect(scopedCounts(['s2'], needs, ready, STATEMENTS)).toEqual({ unresolved: 2, pending_approval: 0, all: 2, posted: 8, settling: 1 })
    expect(scopedCounts(['s1', 's2'], needs, ready, STATEMENTS)).toEqual({ unresolved: 3, pending_approval: 1, all: 4, posted: 12, settling: 1 })
  })
})
