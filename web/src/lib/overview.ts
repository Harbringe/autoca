// Readings of the firm overview that more than one screen needs: what a stage is called, where a
// client's next step is done, and which clients need a person first. Pure, so they are tested.

import type { OverviewClient, Stage } from '@/api/types'

export type StageTone = 'neutral' | 'attention' | 'info' | 'done'

/** Workflow order, left to right on the pipeline board. (The server lists them by precedence.) */
export const STAGES: Stage[] = ['no_statements', 'needs_ledger', 'ready_to_post', 'ready_for_review', 'in_review', 'signed_off']

/** A stage taken from an untrusted value (a query string), or undefined. */
export const parseStage = (value: unknown): Stage | undefined => STAGES.find((s) => s === value)

export const STAGE_LABEL: Record<Stage, string> = {
  no_statements: 'No statements yet',
  needs_ledger: 'Needs a ledger',
  ready_to_post: 'Ready to post',
  ready_for_review: 'Ready for review',
  in_review: 'In review',
  signed_off: 'Signed off',
}

export const STAGE_HINT: Record<Stage, string> = {
  no_statements: 'Nothing uploaded yet.',
  needs_ledger: 'Some rows have no ledger.',
  ready_to_post: 'Every row has a ledger; some are not posted.',
  ready_for_review: 'Posted, and ready to send to the Senior CA.',
  in_review: 'Sent to the Senior CA, who has not decided.',
  signed_off: 'Everything on file is signed off.',
}

export const STAGE_TONE: Record<Stage, StageTone> = {
  no_statements: 'neutral',
  needs_ledger: 'attention',
  ready_to_post: 'info',
  ready_for_review: 'info',
  in_review: 'info',
  signed_off: 'done',
}

/** The screen where a client's next step is done. */
export type NextTarget =
  | { to: '/clients/$clientId/statements'; search?: undefined }
  | { to: '/clients/$clientId/review'; search: { stage: 'unresolved' | 'pending_approval' } }
  | { to: '/clients/$clientId/books'; search?: undefined }
  | { to: '/clients/$clientId'; search?: undefined }

export function nextTarget(code: OverviewClient['next_step']['code']): NextTarget {
  switch (code) {
    case 'upload':
      return { to: '/clients/$clientId/statements' }
    case 'place':
      return { to: '/clients/$clientId/review', search: { stage: 'unresolved' } }
    case 'post':
      return { to: '/clients/$clientId/review', search: { stage: 'pending_approval' } }
    case 'sign_off':
    case 'send_for_review':
      return { to: '/clients/$clientId/books' }
    default:
      return { to: '/clients/$clientId' }
  }
}

/** Books status in the words of the spec, from what the overview knows. "Returned" is not in it. */
export function booksWord(c: Pick<OverviewClient, 'review_pending'>): { label: string; tone: 'neutral' | 'info' } {
  return c.review_pending ? { label: 'Sent for review', tone: 'info' } : { label: 'Working draft', tone: 'neutral' }
}

/** Clients that need a person now: most rows to place first, then most ready to post, then name. */
export function needsAttention(clients: OverviewClient[], limit = 8): OverviewClient[] {
  return clients
    .filter((c) => c.unresolved > 0 || c.pending_approval > 0 || c.review_pending || c.ai_unchecked > 0)
    .sort(
      (a, b) =>
        b.unresolved - a.unresolved ||
        b.pending_approval - a.pending_approval ||
        Number(b.review_pending) - Number(a.review_pending) ||
        b.ai_unchecked - a.ai_unchecked ||
        a.name.localeCompare(b.name),
    )
    .slice(0, limit)
}

/** "Apr 2026, May 2026" from YYYY-MM values. */
export function monthsText(months: string[]): string {
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return months
    .map((m) => {
      const [y, mm] = m.split('-')
      return `${names[Number(mm) - 1] ?? mm} ${y}`
    })
    .join(', ')
}

export const hasWork = (c: Pick<OverviewClient, 'unresolved' | 'pending_approval'>) => c.unresolved > 0 || c.pending_approval > 0
