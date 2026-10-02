// Where a client's books stand in the review workflow.
//
// The server does not store a state; it stores the history of what people did
// and a lock date, and the state is read from those. This is that reading, in
// one place, so every screen that shows "where are the books" agrees.

import type { components } from '@/api/schema'
import { formatDate } from '@/lib/format'

type BooksStatus = components['schemas']['BooksStatus']

export type BooksState = 'draft' | 'awaiting_senior' | 'returned'

export function booksState(status: Pick<BooksStatus, 'review_pending' | 'history'>): BooksState {
  if (status.review_pending) return 'awaiting_senior'
  // History is newest first. A return is the last word until someone acts again.
  const last = status.history[0]
  return last?.action === 'RETURNED' ? 'returned' : 'draft'
}

export const BOOKS_STATE_LABEL: Record<BooksState, string> = {
  draft: 'Working draft',
  awaiting_senior: 'Sent for review',
  returned: 'Returned',
}

export const BOOKS_STATE_TONE: Record<BooksState, 'neutral' | 'warning' | 'danger'> = {
  draft: 'neutral',
  awaiting_senior: 'warning',
  returned: 'danger',
}

export const BOOKS_STATE_HINT: Record<BooksState, string> = {
  draft: 'Not yet sent for review.',
  awaiting_senior: 'Sent for review; not yet signed off or returned.',
  returned: 'Sent back with a note by whoever reviewed them.',
}

/** "Signed off through 31-03-2026", or null while nothing is locked. */
export function lockLabel(status: Pick<BooksStatus, 'signed_off_through'>): string | null {
  return status.signed_off_through ? `Signed off through ${formatDate(status.signed_off_through)}` : null
}

/**
 * The latest statement date not yet inside signed-off books, or null when everything on file is
 * signed off. Posting a new month after a sign-off leaves this set until it is sent and signed.
 */
export function unsignedThrough(status: Pick<BooksStatus, 'signed_off_through'>, latestStatementEnd: string | null): string | null {
  if (!latestStatementEnd) return null
  if (status.signed_off_through && status.signed_off_through >= latestStatementEnd) return null
  return latestStatementEnd
}

export interface SignOffEntry {
  entry_date: string
  marker: string
  lines: { direction: 'DR' | 'CR'; amount_paise: number }[]
}

export interface SignOffPreview {
  vouchers: number
  drPaise: number
  crPaise: number
  /** Assistant-posted or -changed entries on or before the date, not yet checked. */
  unchecked: number
}

/** The latest entry date, or null when there are no entries. */
export function latestEntryDate(entries: Pick<SignOffEntry, 'entry_date'>[]): string | null {
  return entries.reduce<string | null>((max, e) => (!max || e.entry_date > max ? e.entry_date : max), null)
}

/**
 * What signing off through `date` locks: entries after the previous lock and up to the date, with
 * their debit and credit totals; and how many entries up to the date still carry an assistant marker
 * (the server refuses the sign-off while any do, whatever their date within that range).
 */
export function signOffPreview(entries: SignOffEntry[], date: string, previousLock: string | null): SignOffPreview {
  const p: SignOffPreview = { vouchers: 0, drPaise: 0, crPaise: 0, unchecked: 0 }
  for (const e of entries) {
    if (e.entry_date > date) continue
    if (e.marker) p.unchecked += 1
    if (previousLock && e.entry_date <= previousLock) continue
    p.vouchers += 1
    for (const l of e.lines) {
      if (l.direction === 'DR') p.drPaise += l.amount_paise
      else p.crPaise += l.amount_paise
    }
  }
  return p
}
