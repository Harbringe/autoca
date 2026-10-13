// Rows that are alike, grouped so they can be looked at once and posted together: the same payee (or, where none could be read, the same
// narration once its numbers are taken out), placed in the same ledger, going the same way. Free of React so it can be tested.

import type { Classification } from '@/api/types'

export interface SimilarGroup {
  /** Stable key: the payee or narration stem, the ledger and the direction. */
  key: string
  /** What to call it: the payee as printed on the first row, or the start of the narration. */
  label: string
  ledger: string
  ledgerName: string
  /** True when money went out. */
  debit: boolean
  rows: Classification[]
  totalPaise: number
  /** How the rows were placed, by count: a rule, the model, a person. */
  byRule: number
  byModel: number
  byPerson: number
}

/** A row that a person can post in bulk: placed, not yet posted, and not on a party's own account (that one needs bills chosen). */
export const isBulkPostable = (r: Classification): boolean => !!r.ledger && !r.is_posted && !r.on_party_account

const collapse = (text: string) => text.toLowerCase().replace(/\s+/g, ' ').trim()

/** What makes two rows the same payee: the payee read from the narration, else the narration with its numbers and codes taken out. */
export function similarityKey(r: Classification): string {
  const payee = collapse(r.counterparty ?? '')
  if (payee) return `p:${payee}`
  const stem = collapse(r.transaction.narration.replace(/[0-9]+/g, ' ').replace(/[^a-z\s]/gi, ' '))
  return `n:${stem.slice(0, 40)}`
}

const labelOf = (r: Classification): string => (r.counterparty ?? '').trim() || r.transaction.narration.replace(/\s+/g, ' ').trim().slice(0, 50) || 'Rows'

/** The postable rows in groups, the largest group first. Rows that cannot be posted in bulk are left out. */
export function groupSimilar(rows: readonly Classification[]): SimilarGroup[] {
  const by = new Map<string, SimilarGroup>()
  for (const r of rows) {
    if (!isBulkPostable(r)) continue
    const debit = !!r.transaction.is_debit
    const key = `${similarityKey(r)}|${r.ledger}|${debit ? 'out' : 'in'}`
    let g = by.get(key)
    if (!g) {
      g = { key, label: labelOf(r), ledger: r.ledger!, ledgerName: r.ledger_name ?? '', debit, rows: [], totalPaise: 0, byRule: 0, byModel: 0, byPerson: 0 }
      by.set(key, g)
    }
    g.rows.push(r)
    g.totalPaise += r.transaction.amount_paise
    if (r.method === 'RULE') g.byRule += 1
    else if (r.method === 'LLM') g.byModel += 1
    else g.byPerson += 1
  }
  return [...by.values()].sort((a, b) => b.rows.length - a.rows.length || b.totalPaise - a.totalPaise || a.label.localeCompare(b.label))
}

/** The key of the group a row belongs to. */
export const groupKeyOf = (r: Classification): string => `${similarityKey(r)}|${r.ledger}|${r.transaction.is_debit ? 'out' : 'in'}`

/** The rows in `rows` that are like `row`: the same group as it, `row` itself included. */
export function similarTo(row: Classification, rows: readonly Classification[]): Classification[] {
  if (!isBulkPostable(row)) return []
  const key = `${similarityKey(row)}|${row.ledger}|${row.transaction.is_debit ? 'out' : 'in'}`
  return rows.filter((r) => isBulkPostable(r) && `${similarityKey(r)}|${r.ledger}|${r.transaction.is_debit ? 'out' : 'in'}` === key)
}
