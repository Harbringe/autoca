// Reviewing one bank statement at a time: which statements have rows waiting in this stage, how many each, and which is shown.
// Free of React so it can be tested.

import type { Classification, Statement } from '@/api/types'

export interface StatementChoice {
  id: string
  /** The bank account, as named on its statement. */
  label: string
  /** The dates the statement covers, as dd-mm-yyyy to dd-mm-yyyy. */
  period: string
  /** Rows of this statement waiting in the stage being looked at. */
  count: number
}

const dmy = (iso: string) => iso.split('-').reverse().join('-')

/** The statements that have rows in `rows`, oldest first, so a client's year is worked through in order. */
export function statementChoices(statements: readonly Statement[], rows: readonly Classification[]): StatementChoice[] {
  const counts = new Map<string, number>()
  for (const r of rows) counts.set(r.transaction.statement, (counts.get(r.transaction.statement) ?? 0) + 1)
  return statements
    .filter((s) => (counts.get(s.id) ?? 0) > 0)
    .sort((a, b) => a.period_start.localeCompare(b.period_start) || a.period_end.localeCompare(b.period_end))
    .map((s) => ({ id: s.id, label: s.bank_account_label, period: `${dmy(s.period_start)} to ${dmy(s.period_end)}`, count: counts.get(s.id)! }))
}

/**
 * The statement the list is limited to, or null for all of them. `asked` is what the address says: nothing (go to the first statement
 * that has work, when there is more than one), `all`, or a statement's id. A statement that no longer has rows waiting falls back to the first.
 */
export function activeStatement(asked: string | undefined, choices: readonly StatementChoice[]): string | null {
  if (choices.length < 2) return null
  if (asked === 'all') return null
  if (asked && choices.some((c) => c.id === asked)) return asked
  return choices[0]!.id
}
