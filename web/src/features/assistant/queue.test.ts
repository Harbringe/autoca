import { describe, expect, it } from 'vitest'
import type { ReviewSummary } from '@/api/types'
import { assistantLine, assistantShort, IDLE_STATUS, statusFromSummary, type AssistantStatus } from './queue'

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
    expect(assistantLine(status(), 0)).toBe('The assistant is working on your statements in the background, so you can leave this page: reading the narrations… 40 of 120 rows done')
    expect(assistantLine(status({ waiting: 120 }), 0)).toContain('120 rows in line')
    expect(assistantShort(status(), 0)).toBe('Assistant processing 80 rows')
  })
  it('keeps the line moving through the phases as time passes', () => {
    const first = assistantLine(status(), 0)
    const later = assistantLine(status(), 3000)
    expect(later).not.toBe(first)
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
