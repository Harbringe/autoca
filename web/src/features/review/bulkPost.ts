// What "Post all high-confidence" is about to post, worked out from the queue rows so the
// confirmation can say who placed them and for how much before anyone agrees.

import type { Classification } from '@/api/types'

export interface BulkSummary {
  count: number
  byRule: number
  byModel: number
  /** Placed by a person, or by a payee a person confirmed. */
  byPerson: number
  paidOutPaise: number
  paidOut: number
  receivedPaise: number
  received: number
}

/** The rows the HIGH band posts: placed in a ledger, not yet posted, in the high-confidence band, and not on a party's account. */
export const isHighReady = (r: Classification): boolean =>
  r.review_band === 'HIGH' && !!r.ledger && !r.is_posted && !r.on_party_account

export function summariseBulk(rows: Classification[]): BulkSummary {
  const s: BulkSummary = { count: 0, byRule: 0, byModel: 0, byPerson: 0, paidOutPaise: 0, paidOut: 0, receivedPaise: 0, received: 0 }
  for (const r of rows) {
    if (!isHighReady(r)) continue
    s.count += 1
    if (r.method === 'RULE') s.byRule += 1
    else if (r.method === 'LLM') s.byModel += 1
    else s.byPerson += 1
    if (r.transaction.is_debit) {
      s.paidOut += 1
      s.paidOutPaise += r.transaction.amount_paise
    } else {
      s.received += 1
      s.receivedPaise += r.transaction.amount_paise
    }
  }
  return s
}
