// The assistant's queue, seen from the browser.
//
// Rows the rules cannot place wait for the assistant, which a background worker on the server reads in small
// batches whether or not anyone has a page open. The browser only watches: while rows are waiting it looks at the
// review summary every few seconds, and this file turns what the summary says into the words to show. Free of
// React so it can be tested. The hook that polls it and the shared status store are in useAssistant.ts.

import type { ReviewSummary } from '@/api/types'
import { plural } from '@/lib/format'

export type AssistantReason = ReviewSummary['assistant_reason']

export interface AssistantStatus {
  /** `working` while rows are waiting and the assistant can read them; `paused` for a limit or an outage; `idle` otherwise. */
  state: 'working' | 'paused' | 'idle'
  reason: AssistantReason
  /** Rows still waiting for the assistant. */
  waiting: number
  /** The most rows that were waiting in this run, so "40 of 120" has a 120. */
  total: number
  /** When it reads again (epoch ms), while paused. */
  resumeAt: number | null
}

export const IDLE_STATUS: AssistantStatus = { state: 'idle', reason: '', waiting: 0, total: 0, resumeAt: null }

/** Fold what the review summary says into the status the screens show. */
export function statusFromSummary(
  previous: AssistantStatus,
  summary: Pick<ReviewSummary, 'assistant_waiting' | 'assistant_reason' | 'assistant_retry_seconds'>,
  now: number,
): AssistantStatus {
  const waiting = summary.assistant_waiting
  const reason = summary.assistant_reason
  if (waiting <= 0 && reason !== 'assistant_off') return IDLE_STATUS
  const paused = reason === 'rate_limit' || reason === 'daily_limit' || reason === 'provider_down'
  return {
    state: reason === 'assistant_off' ? 'idle' : paused ? 'paused' : 'working',
    reason,
    waiting,
    total: waiting === 0 ? 0 : Math.max(previous.total, waiting),
    resumeAt: paused && summary.assistant_retry_seconds ? now + summary.assistant_retry_seconds * 1000 : null,
  }
}

const secondsLeft = (status: AssistantStatus, now: number) => Math.max(0, Math.ceil(((status.resumeAt ?? now) - now) / 1000))

/** What the assistant is doing, in turn. The line changes every few seconds so a long run reads as live work. */
const PHASES = [
  'reading the narrations',
  'recognising the people and businesses paid',
  'matching rows to this client’s ledgers',
  'checking amounts against the rules',
  'placing rows for your review',
] as const
const PHASE_MS = 3000

export const phaseAt = (now: number): string => PHASES[Math.floor(now / PHASE_MS) % PHASES.length] ?? PHASES[0]

/** True while the assistant is, or is about to be, at work on rows, so the line should keep moving. */
export const isProcessing = (status: AssistantStatus): boolean =>
  status.waiting > 0 && status.reason !== 'assistant_off' && status.reason !== 'daily_limit' && status.reason !== 'provider_down'

/** The sentence for a strip on Bank statements and Review, or null when the assistant has nothing to say. */
export function assistantLine(status: AssistantStatus, now: number): string | null {
  if (status.reason === 'assistant_off') return 'The assistant is off, so rows are placed by rules and by you.'
  if (status.waiting <= 0) return null
  if (status.reason === 'daily_limit') return `Assistant allowance used for today, ${plural(status.waiting, 'row')} left for you`
  if (status.reason === 'provider_down') return `The assistant is not answering. Trying again in ${secondsLeft(status, now)} s`
  // Waiting between batches (a rate limit, or the next batch not yet asked for) is still processing.
  const done = Math.max(0, status.total - status.waiting)
  const progress = done > 0 ? ` ${done} of ${plural(status.total, 'row')} done` : ` ${plural(status.waiting, 'row')} in line`
  return `The assistant is working on your statements in the background, so you can leave this page: ${phaseAt(now)}…${progress}`
}

/** The short form for the top bar, or null when there is nothing to show there. */
export function assistantShort(status: AssistantStatus, _now: number): string | null {
  if (status.waiting <= 0 || status.reason === 'assistant_off') return null
  if (status.reason === 'daily_limit') return 'Assistant: allowance used'
  if (status.reason === 'provider_down') return 'Assistant not answering'
  return `Assistant processing ${plural(status.waiting, 'row')}`
}
