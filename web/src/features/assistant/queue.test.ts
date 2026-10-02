import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { NextBatch } from '@/api/types'
import { assistantLine, assistantShort, IDLE_STATUS, planNext, seeded, startAssistantLoop, statusAfter, type AssistantStatus } from './queue'

const answer = (over: Partial<NextBatch> = {}): NextBatch => ({
  processed: 10,
  suggested: 8,
  declined: 2,
  waiting: 20,
  state: 'working',
  retry_after_seconds: null,
  reason: '',
  message: '',
  auto_posted: 0,
  proposed: 0,
  ...over,
})
const status = (over: Partial<AssistantStatus> = {}): AssistantStatus => ({ ...IDLE_STATUS, state: 'working', waiting: 80, total: 120, ...over })

describe('planNext', () => {
  it('calls again after 3 s when the server names no pause', () => {
    expect(planNext(answer())).toEqual({ stop: false, delayMs: 3000 })
  })
  it('waits as long as a paused answer says, but no less than 1 s and no more than 60 s', () => {
    expect(planNext(answer({ state: 'paused', retry_after_seconds: 40 }))).toEqual({ stop: false, delayMs: 40_000 })
    expect(planNext(answer({ state: 'paused', retry_after_seconds: 0 }))).toEqual({ stop: false, delayMs: 1000 })
    expect(planNext(answer({ state: 'paused', retry_after_seconds: 7200 }))).toEqual({ stop: false, delayMs: 60_000 })
  })
  it('stops when idle or nothing is left', () => {
    expect(planNext(answer({ state: 'idle', waiting: 5 }))).toEqual({ stop: true })
    expect(planNext(answer({ waiting: 0 }))).toEqual({ stop: true })
  })
})

describe('statusAfter and seeded', () => {
  it('keeps the largest waiting count as the total, and clears it at zero', () => {
    const first = statusAfter(seeded(IDLE_STATUS, 120), answer({ waiting: 110 }), 0)
    expect(first.total).toBe(120)
    expect(statusAfter(first, answer({ waiting: 0, state: 'idle' }), 0).total).toBe(0)
  })
  it('sets a resume time only while paused', () => {
    expect(statusAfter(IDLE_STATUS, answer({ state: 'paused', reason: 'rate_limit', retry_after_seconds: 40 }), 1000).resumeAt).toBe(41_000)
    expect(statusAfter(IDLE_STATUS, answer(), 1000).resumeAt).toBeNull()
  })
})

describe('the words', () => {
  it('says how far the assistant has got', () => {
    expect(assistantLine(status(), 0)).toBe('The assistant is reading 40 of 120 rows')
    expect(assistantLine(status({ waiting: 120 }), 0)).toBe('The assistant is reading 120 rows')
    expect(assistantShort(status(), 0)).toBe('Assistant reading 80 rows')
  })
  it('counts down a rate-limit pause', () => {
    const paused = status({ state: 'paused', reason: 'rate_limit', resumeAt: 40_000 })
    expect(assistantLine(paused, 0)).toBe('Paused: rate limit, resuming in 40 s')
    expect(assistantLine(paused, 39_500)).toBe('Paused: rate limit, resuming in 1 s')
    expect(assistantShort(paused, 10_000)).toBe('Assistant paused, 30 s')
  })
  it('names the daily allowance and what is left for a person', () => {
    const spent = status({ state: 'paused', reason: 'daily_limit', waiting: 30 })
    expect(assistantLine(spent, 0)).toBe('Assistant allowance used for today, 30 rows left for you')
    expect(assistantShort(spent, 0)).toBe('Assistant: allowance used')
  })
  it('says so when the assistant is off, and is silent when nothing waits', () => {
    expect(assistantLine(status({ state: 'idle', reason: 'assistant_off' }), 0)).toBe('The assistant is off, so rows are placed by rules and by you.')
    expect(assistantShort(status({ state: 'idle', reason: 'assistant_off' }), 0)).toBeNull()
    expect(assistantLine(IDLE_STATUS, 0)).toBeNull()
  })
})

describe('startAssistantLoop', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('asks, waits as told, asks again, and stops at idle', async () => {
    const answers = [answer({ waiting: 20 }), answer({ state: 'paused', reason: 'rate_limit', retry_after_seconds: 40, waiting: 20, processed: 0 }), answer({ state: 'idle', waiting: 0 })]
    const post = vi.fn(async () => answers.shift()!)
    const onOutcome = vi.fn()
    const onDone = vi.fn()
    startAssistantLoop({ post, onOutcome, onError: () => true, onDone })
    await vi.advanceTimersByTimeAsync(0)
    expect(post).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2999)
    expect(post).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(post).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(39_999)
    expect(post).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(post).toHaveBeenCalledTimes(3)
    expect(onOutcome).toHaveBeenCalledTimes(3)
    expect(onDone).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(120_000)
    expect(post).toHaveBeenCalledTimes(3)
  })

  it('stops for good when told to (a hidden tab, or leaving the client), even with a call in flight', async () => {
    let release: (value: NextBatch) => void = () => {}
    const post = vi.fn(() => new Promise<NextBatch>((resolve) => (release = resolve)))
    const onOutcome = vi.fn()
    const stop = startAssistantLoop({ post, onOutcome, onError: () => true })
    await vi.advanceTimersByTimeAsync(0)
    stop()
    release(answer())
    await vi.advanceTimersByTimeAsync(60_000)
    expect(onOutcome).not.toHaveBeenCalled()
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('tries again after 30 s when a call fails, and gives up when told the failure is final', async () => {
    const post = vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(answer({ state: 'idle', waiting: 0 }))
    const onDone = vi.fn()
    startAssistantLoop({ post, onOutcome: () => {}, onError: () => true, onDone })
    await vi.advanceTimersByTimeAsync(29_999)
    expect(post).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(post).toHaveBeenCalledTimes(2)
    expect(onDone).toHaveBeenCalledTimes(1)

    const fatal = vi.fn().mockRejectedValue(new Error('403'))
    const done = vi.fn()
    startAssistantLoop({ post: fatal, onOutcome: () => {}, onError: () => false, onDone: done })
    await vi.advanceTimersByTimeAsync(120_000)
    expect(fatal).toHaveBeenCalledTimes(1)
    expect(done).toHaveBeenCalledTimes(1)
  })
})
