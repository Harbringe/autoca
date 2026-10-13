// Reviewing a bank statement from the statement itself: how much of it is waiting, and where its Review button goes. Free of React so it can be tested.

import type { Classification } from '@/api/types'

export interface Waiting {
  /** Rows with no ledger yet. */
  needs: number
  /** Rows placed, waiting to be posted. */
  ready: number
}

/** What is waiting in each statement, by its id. A statement with nothing waiting is not in the map. */
export function waitingByStatement(unresolved: readonly Classification[], pending: readonly Classification[]): Map<string, Waiting> {
  const by = new Map<string, Waiting>()
  const bump = (id: string, key: keyof Waiting) => by.set(id, { needs: 0, ready: 0, ...by.get(id), [key]: (by.get(id)?.[key] ?? 0) + 1 })
  for (const r of unresolved) bump(r.transaction.statement, 'needs')
  for (const r of pending) bump(r.transaction.statement, 'ready')
  return by
}

/** The words for what is waiting, or null when the statement is all posted. */
export function waitingWords(w: Waiting | undefined): string | null {
  if (!w || (w.needs === 0 && w.ready === 0)) return null
  const parts: string[] = []
  if (w.needs) parts.push(`${w.needs} need${w.needs === 1 ? 's' : ''} a ledger`)
  if (w.ready) parts.push(`${w.ready} ready to post`)
  return parts.join(' · ')
}

/** The stage the Review button opens: the rows needing a ledger first, else the ones ready to post. */
export const reviewStage = (w: Waiting | undefined): 'unresolved' | 'pending_approval' => (w && w.needs > 0 ? 'unresolved' : 'pending_approval')
