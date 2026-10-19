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
  /** `working` while rows are waiting and the assistant can read them; `paused` for a limit, an outage or a person's pause; `idle` otherwise. */
  state: 'working' | 'paused' | 'idle'
  reason: AssistantReason
  /** Rows still waiting for the assistant. */
  waiting: number
  /** The most rows that were waiting in this run, so "40 of 120" has a 120. */
  total: number
  /** When it reads again (epoch ms), while paused. */
  resumeAt: number | null
  /** When this run began (epoch ms): the first time rows were seen waiting after none were. */
  startedAt?: number | null
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
  // A person's pause is shown even with nothing waiting: the button to resume has to stay, and a later upload would not be read.
  if (reason === 'paused_by_person') return { state: 'paused', reason, waiting, total: 0, resumeAt: null, startedAt: null }
  if (waiting <= 0 && reason !== 'assistant_off') return IDLE_STATUS
  const paused = reason === 'rate_limit' || reason === 'daily_limit' || reason === 'provider_down'
  return {
    state: reason === 'assistant_off' ? 'idle' : paused ? 'paused' : 'working',
    reason,
    waiting,
    total: waiting === 0 ? 0 : Math.max(previous.total, waiting),
    resumeAt: paused && summary.assistant_retry_seconds ? now + summary.assistant_retry_seconds * 1000 : null,
    // A run starts when rows are first seen waiting after none were; it carries on until the queue empties.
    startedAt: previous.waiting > 0 ? (previous.startedAt ?? now) : now,
  }
}

const secondsLeft = (status: AssistantStatus, now: number) => Math.max(0, Math.ceil(((status.resumeAt ?? now) - now) / 1000))

/** True while the assistant is, or is about to be, at work on rows, so the line should keep moving. */
export const isProcessing = (status: AssistantStatus): boolean =>
  status.waiting > 0 &&
  status.reason !== 'assistant_off' &&
  status.reason !== 'daily_limit' &&
  status.reason !== 'provider_down' &&
  status.reason !== 'paused_by_person'

/** True while a person has paused the assistant for this client. */
export const isPausedByPerson = (status: AssistantStatus): boolean => status.reason === 'paused_by_person'

/** The sentence for a strip on Bank statements and Review, or null when the assistant has nothing to say. */
export function assistantLine(status: AssistantStatus, now: number): string | null {
  if (status.reason === 'assistant_off') return 'The assistant is off, so rows are placed by rules and by you.'
  if (status.reason === 'paused_by_person')
    return status.waiting > 0 ? `Assistant paused: ${plural(status.waiting, 'row')} wait until you resume it` : 'Assistant paused for this client'
  if (status.waiting <= 0) return null
  if (status.reason === 'daily_limit') return `Assistant allowance used for today, ${plural(status.waiting, 'row')} left for you`
  if (status.reason === 'provider_down') return `The assistant is not answering. Trying again in ${secondsLeft(status, now)} s`
  // Waiting between batches (a rate limit, or the next batch not yet asked for) is still processing.
  const done = Math.max(0, status.total - status.waiting)
  if (done > 0) return `Assistant at work: ${done} of ${plural(status.total, 'row')} done`
  // Nothing has come back yet: a batch is a few dozen rows written out by the model, which takes a while. Say that, with the time so far,
  // rather than a changing phrase that suggests steps that are not being reported.
  const seconds = status.startedAt ? Math.max(0, Math.floor((now - status.startedAt) / 1000)) : 0
  return seconds >= 3
    ? `Assistant at work: waiting for the first answers (${seconds} s) · ${plural(status.waiting, 'row')} in line`
    : `Assistant at work: ${plural(status.waiting, 'row')} in line`
}

/** The short form for the top bar, or null when there is nothing to show there. */
export function assistantShort(status: AssistantStatus, _now: number): string | null {
  if (status.reason === 'paused_by_person') return 'Assistant paused'
  if (status.waiting <= 0 || status.reason === 'assistant_off') return null
  if (status.reason === 'daily_limit') return 'Assistant: allowance used'
  if (status.reason === 'provider_down') return 'Assistant not answering'
  return `Assistant processing ${plural(status.waiting, 'row')}`
}
