import { describe, expect, it } from 'vitest'
import type { Classification, Statement } from '@/api/types'
import { activeStatement, statementChoices } from './statementChoices'

const statement = (id: string, label: string, start: string, end: string) => ({ id, bank_account_label: label, period_start: start, period_end: end }) as unknown as Statement
const row = (n: number, statementId: string) => ({ id: `r${n}`, transaction: { statement: statementId } }) as unknown as Classification

const STATEMENTS = [
  statement('s2', 'Icici Bank A/c 7921', '2025-04-03', '2026-03-31'),
  statement('s1', 'Generic Bank A/c 5335', '2025-01-01', '2025-03-31'),
  statement('s3', 'Empty one', '2024-01-01', '2024-03-31'),
]

describe('statements to review one at a time', () => {
  it('lists the statements that have rows waiting, oldest first, with how many', () => {
    const choices = statementChoices(STATEMENTS, [row(1, 's2'), row(2, 's2'), row(3, 's1')])
    expect(choices.map((c) => [c.id, c.count])).toEqual([['s1', 1], ['s2', 2]])
    expect(choices[0]).toMatchObject({ label: 'Generic Bank A/c 5335', period: '01-01-2025 to 31-03-2025' })
  })

  it('leaves out a statement with nothing waiting, and rows of a statement that is not known', () => {
    expect(statementChoices(STATEMENTS, [row(1, 'nowhere')])).toEqual([])
  })

  it('goes to the first statement unless told otherwise, and to all of them only when there is more than one to choose between', () => {
    const two = statementChoices(STATEMENTS, [row(1, 's2'), row(2, 's1')])
    expect(activeStatement(undefined, two)).toBe('s1')
    expect(activeStatement('s2', two)).toBe('s2')
    expect(activeStatement('all', two)).toBeNull()
    expect(activeStatement('gone', two)).toBe('s1')
    // with one statement there is nothing to choose between
    expect(activeStatement(undefined, statementChoices(STATEMENTS, [row(1, 's2')]))).toBeNull()
    expect(activeStatement('s2', [])).toBeNull()
  })
})
