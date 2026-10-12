// Small readings the sign-off checklist needs: the headline sentence, and the one figure to show beside a check.
// The server words each control's detail from a fixed template, so the leading count and the difference are read
// from it; when the wording does not match, no figure is shown and the full detail still is.

import type { BooksState } from './state'

export interface CheckLike {
  name: string
  ok: boolean
  detail: string
}

/** The figure shown at the right of a check row, or null when the detail does not carry one. */
export function checkFigure(check: CheckLike): string | null {
  if (check.ok) return null
  if (check.name === 'rows_posted') {
    const n = /^(\d+)\s/.exec(check.detail)?.[1]
    return n ? `${n} to decide` : null
  }
  if (check.name === 'assistant_entries_checked') {
    const n = /^(\d+)\s/.exec(check.detail)?.[1]
    return n ? `${n} to check` : null
  }
  if (check.name.startsWith('bank_')) {
    return /difference is (₹[\d,]+(?:\.\d+)?)/.exec(check.detail)?.[1] ?? null
  }
  return null
}

/** The first sentence of a check's detail, without its full stop: the one line shown under the check's title. */
export function firstSentence(detail: string): string {
  return (detail.split('. ')[0] ?? '').replace(/\.$/, '')
}

/** What the detail says after its first sentence, or an empty string when the first sentence was all of it. */
export function restAfterFirst(detail: string): string {
  const at = detail.indexOf('. ')
  return at === -1 ? '' : detail.slice(at + 2).trim()
}

/** The three figures of a bank check, read from its wording, with the count of unposted transactions when it names one. */
export function bankFigures(detail: string): { books: string; bank: string; difference: string; unposted: string | null } | null {
  const m = /books say (₹[\d,]+(?:\.\d+)?); the bank says (₹[\d,]+(?:\.\d+)?); the difference is (₹[\d,]+(?:\.\d+)?)/.exec(detail)
  if (!m) return null
  return { books: m[1]!, bank: m[2]!, difference: m[3]!, unposted: /(\d+) transaction\(s\) up to that date have not been posted/.exec(detail)?.[1] ?? null }
}

export interface HeadlineInput {
  state: BooksState
  /** Failing controls plus blocking items nobody has explained. */
  toClear: number
  /** The report has arrived. */
  known: boolean
  leadName?: string | null
  nextSealDate?: string | null
}

const WORDS = ['No things', 'One thing', 'Two things', 'Three things', 'Four things', 'Five things']

export function signOffHeadline({ state, toClear, known, leadName, nextSealDate }: HeadlineInput): string {
  if (state === 'awaiting_senior') return `The books are with ${leadName ?? 'the senior'} for approval.`
  if (state === 'approved') return nextSealDate ? `The books are approved. They will be sealed on ${nextSealDate}.` : 'The books are approved and waiting to be sealed.'
  if (state === 'returned') return 'The books were returned with a note. Fix what it asks for, then send them again.'
  if (!known) return 'Checking what is open…'
  if (toClear === 0) return 'Every check passes. You can send the books for review.'
  const what = WORDS[toClear] ?? `${toClear} things`
  return `${what} to clear before you can send the books for review.`
}
