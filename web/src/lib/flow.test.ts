import { describe, expect, it } from 'vitest'
import type { WorkFlow } from '@/api/types'
import { flowSentence, markPartial, weekLabel } from './flow'

const flow = (over: Partial<WorkFlow> = {}): WorkFlow =>
  ({
    scope: 'firm',
    period: { from: '2026-07-22', to: '2026-10-07' },
    weekly: [
      { week_start: '2026-07-20', received: 10, finished: 8 },
      { week_start: '2026-07-27', received: 20, finished: 25 },
      { week_start: '2026-10-05', received: 5, finished: 4 },
    ],
    totals: { received: 35, finished: 37, prev_received: 30, prev_finished: 28 },
    ...over,
  }) as WorkFlow

describe('the weekly work-flow wording', () => {
  it('says what the numbers are and never claims a backlog or a lead', () => {
    const text = flowSentence(flow())
    expect(text).toContain('Finished 37 entries and received 35 rows')
    expect(text.toLowerCase()).not.toMatch(/backlog|building|piling|behind|ahead/)
  })
  it('uses the singular for one week', () => {
    expect(flowSentence(flow({ weekly: [{ week_start: '2026-10-05', received: 1, finished: 1 }] }))).toContain('this week')
  })
  it('marks the first and last weeks as partial when they run outside the period', () => {
    const weeks = markPartial(flow())
    expect(weeks.map((w) => w.partial)).toEqual([true, false, true])
  })
  it('labels a week as day and month', () => {
    expect(weekLabel('2026-10-05')).toBe('5 Oct')
  })
})
