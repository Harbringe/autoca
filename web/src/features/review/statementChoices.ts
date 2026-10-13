// Reviewing by bank statement: which statements have rows waiting, which are chosen (one, several, or all), and the counts that follow
// from the choice. Free of React so it can be tested.
//
// The choice lives in the address as `statement`: `all`, or one or more statement ids joined with commas. Nothing in the address means
// "start with the oldest statement that has work" when there is more than one to choose between.

import type { Classification, Statement } from '@/api/types'

export interface StatementChoice {
  id: string
  /** The bank account, as named on its statement. */
  label: string
  /** The dates the statement covers, as dd-mm-yyyy to dd-mm-yyyy. */
  period: string
  /** Rows of this statement waiting (in the rows given). */
  count: number
}

const dmy = (iso: string) => iso.split('-').reverse().join('-')

function choicesFrom(statements: readonly Statement[], rows: readonly Classification[]): StatementChoice[] {
  const counts = new Map<string, number>()
  for (const r of rows) counts.set(r.transaction.statement, (counts.get(r.transaction.statement) ?? 0) + 1)
  return statements
    .filter((s) => (counts.get(s.id) ?? 0) > 0)
    .sort((a, b) => a.period_start.localeCompare(b.period_start) || a.period_end.localeCompare(b.period_end))
    .map((s) => ({ id: s.id, label: s.bank_account_label, period: `${dmy(s.period_start)} to ${dmy(s.period_end)}`, count: counts.get(s.id)! }))
}

/** The statements that have rows in `rows`, oldest first, so a client's year is worked through in order. */
export const statementChoices = choicesFrom

/** The statements with anything waiting in either queue (needing a ledger, or ready to post), oldest first, with how many. */
export const waitingStatements = (statements: readonly Statement[], needs: readonly Classification[], ready: readonly Classification[]): StatementChoice[] =>
  choicesFrom(statements, [...needs, ...ready])

/**
 * The statements chosen, or null for all of them. `asked` is what the address says. Ids that are not statements of this client are ignored;
 * with nothing usable asked, the oldest statement with work is chosen when there is more than one to choose between.
 */
export function resolveSelection(asked: string | undefined, waiting: readonly StatementChoice[], statements: readonly Statement[]): string[] | null {
  if (asked === 'all') return null
  const known = new Set(statements.map((s) => s.id))
  const named = (asked ?? '')
    .split(',')
    .map((id) => id.trim())
    .filter((id, i, all) => known.has(id) && all.indexOf(id) === i)
  if (named.length) return named
  return waiting.length > 1 ? [waiting[0]!.id] : null
}

/** The address value for a choice: `all` for everything, else the ids. */
export const askedOf = (selection: readonly string[] | null): string => (selection && selection.length ? selection.join(',') : 'all')

/** The address value after the person ticks or unticks `id`. The last one cannot be unticked, and ticking them all is `all`. */
export function toggled(selection: readonly string[] | null, id: string, waiting: readonly StatementChoice[]): string {
  const everyId = waiting.map((c) => c.id)
  const current = selection ?? everyId
  const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
  if (next.length === 0) return askedOf(current)
  if (everyId.length > 0 && everyId.every((x) => next.includes(x))) return 'all'
  // Keep them in the order the statements are listed (oldest first), so the address does not depend on the order of clicks.
  return askedOf(everyId.filter((x) => next.includes(x)).concat(next.filter((x) => !everyId.includes(x))))
}

export interface ScopedCounts {
  /** Rows needing a ledger, in the chosen statements. */
  unresolved: number
  /** Rows placed and ready to post. */
  pending_approval: number
  /** Everything not yet posted. */
  all: number
  /** Rows already in the books. */
  posted: number
  /** Rows on a party's own account, each needing to be settled by hand. */
  settling: number
}

/**
 * The review's numbers for the statements chosen, or null when it is all of them (then the client's own totals are the numbers).
 * Posted is what is on file in these statements less what is still waiting.
 */
export function scopedCounts(
  selection: readonly string[] | null,
  needs: readonly Classification[],
  ready: readonly Classification[],
  statements: readonly Statement[],
): ScopedCounts | null {
  if (!selection) return null
  const chosen = new Set(selection)
  const inChosen = (r: Classification) => chosen.has(r.transaction.statement)
  const n = needs.filter(inChosen)
  const p = ready.filter(inChosen)
  const onFile = statements.filter((s) => chosen.has(s.id)).reduce((sum, s) => sum + s.transaction_count, 0)
  return {
    unresolved: n.length,
    pending_approval: p.length,
    all: n.length + p.length,
    posted: Math.max(0, onFile - n.length - p.length),
    settling: [...n, ...p].filter((r) => r.on_party_account).length,
  }
}

/** The words under the picker: the chosen statements' periods, or how many there are. */
export function selectionSummary(selection: readonly string[] | null, waiting: readonly StatementChoice[]): string {
  if (!selection) return `${waiting.length} statements, worked through one at a time or all together`
  const chosen = waiting.filter((c) => selection.includes(c.id))
  if (chosen.length === 1) return chosen[0]!.period
  return `${selection.length} statements chosen`
}
