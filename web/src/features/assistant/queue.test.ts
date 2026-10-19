import { describe, expect, it } from 'vitest'
import type { ReviewSummary } from '@/api/types'
import { assistantLine, assistantShort, IDLE_STATUS, isPausedByPerson, isProcessing, statusFromSummary, type AssistantStatus } from './queue'

const status = (over: Partial<AssistantStatus> = {}): AssistantStatus => ({ ...IDLE_STATUS, state: 'working', waiting: 80, total: 120, ...over })

const summary = (over: Partial<Pick<ReviewSummary, 'assistant_waiting' | 'assistant_reason' | 'assistant_retry_seconds'>> = {}) => ({
  assistant_waiting: 20,
  assistant_reason: '' as const,
  assistant_retry_seconds: null,
  ...over,
})

describe('statusFromSummary', () => {
  it('is working while rows wait, and remembers how many there were at the start', () => {
    const first = statusFromSummary(IDLE_STATUS, summary({ assistant_waiting: 120 }), 0)
    expect(first).toMatchObject({ state: 'working', waiting: 120, total: 120 })
    expect(statusFromSummary(first, summary({ assistant_waiting: 80 }), 0)).toMatchObject({ waiting: 80, total: 120 })
  })
  it('goes quiet when nothing waits', () => {
    expect(statusFromSummary(status(), summary({ assistant_waiting: 0 }), 0)).toEqual(IDLE_STATUS)
  })
  it('is paused with a time to resume for a limit or an outage', () => {
    const limited = statusFromSummary(IDLE_STATUS, summary({ assistant_reason: 'rate_limit', assistant_retry_seconds: 40 }), 1000)
    expect(limited).toMatchObject({ state: 'paused', reason: 'rate_limit', resumeAt: 41_000 })
  })
  it('is idle but says so when the assistant is off', () => {
    expect(statusFromSummary(IDLE_STATUS, summary({ assistant_reason: 'assistant_off', assistant_waiting: 5 }), 0)).toMatchObject({ state: 'idle', reason: 'assistant_off' })
  })
})

describe('the words', () => {
  it('says the assistant is processing, with how far it has got', () => {
    expect(assistantLine(status(), 0)).toBe('Assistant at work: 40 of 120 rows done')
    expect(assistantLine(status({ waiting: 120 }), 0)).toContain('120 rows in line')
    expect(assistantShort(status(), 0)).toBe('Assistant processing 80 rows')
  })
  it('counts the seconds while nothing has come back yet, and says what it is waiting for', () => {
    const none = status({ waiting: 120, total: 120, startedAt: 10_000 })
    expect(assistantLine(none, 11_000)).toBe('Assistant at work: 120 rows in line')
    expect(assistantLine(none, 47_000)).toBe('Assistant at work: waiting for the first answers (37 s) · 120 rows in line')
    // once rows come back the count of rows is the news, not the clock
    expect(assistantLine(status({ waiting: 100, total: 120, startedAt: 10_000 }), 47_000)).toBe('Assistant at work: 20 of 120 rows done')
  })
  it('starts the clock when rows are first seen waiting, and keeps it through the run', () => {
    const first = statusFromSummary(IDLE_STATUS, summary({ assistant_waiting: 120 }), 5_000)
    expect(first.startedAt).toBe(5_000)
    expect(statusFromSummary(first, summary({ assistant_waiting: 90 }), 40_000).startedAt).toBe(5_000)
    // a new run after the queue emptied starts again
    expect(statusFromSummary(IDLE_STATUS, summary({ assistant_waiting: 10 }), 90_000).startedAt).toBe(90_000)
  })
  it('never says paused while it waits between batches', () => {
    const waiting = status({ state: 'paused', reason: 'rate_limit', resumeAt: 40_000 })
    expect(assistantLine(waiting, 0)).not.toMatch(/paus/i)
    expect(assistantShort(waiting, 10_000)).toBe('Assistant processing 80 rows')
  })
  it('is honest when the provider is not answering', () => {
    const down = status({ state: 'paused', reason: 'provider_down', resumeAt: 30_000 })
    expect(assistantLine(down, 0)).toBe('The assistant is not answering. Trying again in 30 s')
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

describe('a pause a person chose', () => {
  it('is paused with no time to resume, and stays visible with nothing waiting (so Resume stays)', () => {
    const held = statusFromSummary(status(), summary({ assistant_reason: 'paused_by_person', assistant_waiting: 40 }), 1000)
    expect(held).toMatchObject({ state: 'paused', reason: 'paused_by_person', waiting: 40, resumeAt: null })
    expect(isPausedByPerson(held)).toBe(true)
    expect(isProcessing(held)).toBe(false)
    const empty = statusFromSummary(status(), summary({ assistant_reason: 'paused_by_person', assistant_waiting: 0 }), 1000)
    expect(empty.state).toBe('paused')
  })
  it('says so in words, with and without rows waiting, and in the top bar', () => {
    const held = statusFromSummary(IDLE_STATUS, summary({ assistant_reason: 'paused_by_person', assistant_waiting: 40 }), 0)
    expect(assistantLine(held, 0)).toBe('Assistant paused: 40 rows wait until you resume it')
    expect(assistantShort(held, 0)).toBe('Assistant paused')
    const none = statusFromSummary(IDLE_STATUS, summary({ assistant_reason: 'paused_by_person', assistant_waiting: 0 }), 0)
    expect(assistantLine(none, 0)).toBe('Assistant paused for this client')
  })
  it('is over as soon as the summary stops saying it', () => {
    const resumed = statusFromSummary(IDLE_STATUS, summary({ assistant_reason: '', assistant_waiting: 40 }), 0)
    expect(resumed.state).toBe('working')
    expect(isPausedByPerson(resumed)).toBe(false)
  })
})
