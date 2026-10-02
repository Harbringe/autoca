// The assistant's queue, seen from the browser.
//
// Rows the rules cannot place wait for the assistant, which reads a few at a time when asked
// (POST /clients/{id}/assistant/next-batch/). The browser is the driver: while a client is open and
// rows are waiting it asks, then asks again after the pause the server names, and stops when the
// server says it is idle. This file is the logic of that, free of React so it can be tested:
// what to do after an answer, the words to show, and the loop itself. The hook that runs it and the
// shared status store are in useAssistant.ts.

import type { NextBatch } from '@/api/types'
import { plural } from '@/lib/format'

/** The pause between calls when the server names none, and the longest we wait before looking again. */
export const DEFAULT_DELAY_S = 3
export const MAX_DELAY_S = 60
/** After a failed call (network, server error) we look again this much later. */
export const ERROR_DELAY_S = 30

export type AssistantReason = NextBatch['reason']

export interface AssistantStatus {
  /** The server's last word. `working` also covers "not asked yet, rows are waiting". */
  state: 'working' | 'paused' | 'idle'
  reason: AssistantReason
  /** The server's own sentence for the last answer. */
  message: string
  /** Rows still waiting for the assistant. */
  waiting: number
  /** The most rows that were waiting in this run, so "40 of 120" has a 120. */
  total: number
  /** When the next call is due (epoch ms), while paused. */
  resumeAt: number | null
  /** A loop is running for this client in this window. */
  running: boolean
}

export const IDLE_STATUS: AssistantStatus = { state: 'idle', reason: '', message: '', waiting: 0, total: 0, resumeAt: null, running: false }

/** What to do after an answer: stop, or call again after `delayMs`. */
export function planNext(outcome: Pick<NextBatch, 'state' | 'waiting' | 'retry_after_seconds'>): { stop: true } | { stop: false; delayMs: number } {
  if (outcome.state === 'idle' || outcome.waiting <= 0) return { stop: true }
  const seconds = Math.min(MAX_DELAY_S, Math.max(1, outcome.retry_after_seconds ?? DEFAULT_DELAY_S))
  return { stop: false, delayMs: seconds * 1000 }
}

/** Fold a server answer into the status the screens show. */
export function statusAfter(previous: AssistantStatus, outcome: NextBatch, now: number): AssistantStatus {
  const next = planNext(outcome)
  return {
    state: outcome.state,
    reason: outcome.reason,
    message: outcome.message,
    waiting: outcome.waiting,
    total: outcome.waiting === 0 ? 0 : Math.max(previous.total, outcome.waiting),
    resumeAt: !next.stop && outcome.state === 'paused' ? now + next.delayMs : null,
    running: previous.running,
  }
}

/** A status for rows the summary says are waiting, before the assistant has been asked. */
export function seeded(previous: AssistantStatus, waiting: number): AssistantStatus {
  if (waiting <= 0) return { ...IDLE_STATUS, running: previous.running }
  return { ...previous, waiting, total: Math.max(previous.total, waiting) }
}

const secondsLeft = (status: AssistantStatus, now: number) => Math.max(0, Math.ceil(((status.resumeAt ?? now) - now) / 1000))

/** The sentence for a strip on Bank statements and Review, or null when the assistant has nothing to say. */
export function assistantLine(status: AssistantStatus, now: number): string | null {
  if (status.reason === 'assistant_off') return 'The assistant is off, so rows are placed by rules and by you.'
  if (status.waiting <= 0) return null
  if (status.reason === 'daily_limit') return `Assistant allowance used for today, ${plural(status.waiting, 'row')} left for you`
  if (status.state === 'paused') {
    if (status.reason === 'rate_limit') return `Paused: rate limit, resuming in ${secondsLeft(status, now)} s`
    if (status.reason === 'provider_down') return `The assistant is not answering. Trying again in ${secondsLeft(status, now)} s`
    return status.message || `Paused, resuming in ${secondsLeft(status, now)} s`
  }
  const done = Math.max(0, status.total - status.waiting)
  return done > 0 ? `The assistant is reading ${done} of ${plural(status.total, 'row')}` : `The assistant is reading ${plural(status.waiting, 'row')}`
}

/** The short form for the top bar, or null when there is nothing to show there. */
export function assistantShort(status: AssistantStatus, now: number): string | null {
  if (status.waiting <= 0 || status.reason === 'assistant_off') return null
  if (status.reason === 'daily_limit') return 'Assistant: allowance used'
  if (status.state === 'paused') return `Assistant paused, ${secondsLeft(status, now)} s`
  return `Assistant reading ${plural(status.waiting, 'row')}`
}

export interface LoopDeps {
  /** Ask for the next batch. */
  post: () => Promise<NextBatch>
  onOutcome: (outcome: NextBatch) => void
  /** A call failed. Return true to keep trying after ERROR_DELAY_S, false to stop for good. */
  onError: (error: unknown) => boolean
  /** Called once when the loop ends by itself (idle, nothing waiting, or a fatal error). */
  onDone?: () => void
}

/**
 * Ask, then ask again as the server says, until it is idle. Returns a function that stops it: a
 * hidden tab and leaving the client both stop it, and an answer that arrives after that is ignored.
 */
export function startAssistantLoop(deps: LoopDeps): () => void {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined

  const later = (ms: number) => {
    timer = setTimeout(() => void step(), ms)
  }
  const step = async () => {
    let outcome: NextBatch
    try {
      outcome = await deps.post()
    } catch (error) {
      if (stopped) return
      if (deps.onError(error)) later(ERROR_DELAY_S * 1000)
      else deps.onDone?.()
      return
    }
    if (stopped) return
    deps.onOutcome(outcome)
    const next = planNext(outcome)
    if (next.stop) deps.onDone?.()
    else later(next.delayMs)
  }
  void step()
  return () => {
    stopped = true
    if (timer !== undefined) clearTimeout(timer)
  }
}
