import { describe, expect, it } from 'vitest'
import type { Classification } from '@/api/types'
import { ideasOf, runLimited } from './ledgerIdeas'

let n = 0
const row = (suggestion: Record<string, unknown> | null, over: Record<string, unknown> = {}): Classification => {
  n += 1
  return { id: `r${n}`, ledger: null, is_posted: false, method: 'UNRESOLVED', suggested_ledger: suggestion, ...over } as unknown as Classification
}
const idea = (name: string, existing: string | null = null) => ({ name, group: 'INDIRECT_EXPENSE', existing_ledger: existing, existing_name: existing ? name : null, rows_sharing: 0 })

describe('the assistant’s ledger ideas', () => {
  it('are grouped by idea, the one with most rows first, a ledger that exists kept apart from one to create', () => {
    const ideas = ideasOf([row(idea('Bank Interest')), row(idea('bank interest')), row(idea('Fuel')), row(idea('Fuel')), row(idea('Fuel')), row(idea('Telephone', 'l9'))])
    expect(ideas.map((i) => [i.name, i.rows.length, i.existingLedger])).toEqual([['Fuel', 3, null], ['Bank Interest', 2, null], ['Telephone', 1, 'l9']])
  })

  it('leave out rows with no idea, rows already in a ledger, posted rows, and rows a person placed', () => {
    expect(ideasOf([row(null), row(idea('X'), { ledger: 'l1' }), row(idea('X'), { is_posted: true }), row(idea('X'), { method: 'REVIEWED' })])).toEqual([])
  })
})

describe('running tasks a few at a time', () => {
  it('runs them all, never more than the limit at once, and counts the ones that fail', async () => {
    let running = 0
    let peak = 0
    const task = (fail: boolean) => async () => {
      running += 1
      peak = Math.max(peak, running)
      await new Promise((r) => setTimeout(r, 2))
      running -= 1
      if (fail) throw new Error('no')
    }
    const seen: number[] = []
    const result = await runLimited([task(false), task(true), task(false), task(false), task(true), task(false)], 3, (done, failed) => seen.push(done + failed))
    expect(result).toEqual({ done: 4, failed: 2 })
    expect(peak).toBeLessThanOrEqual(3)
    expect(seen.at(-1)).toBe(6)
  })

  it('does nothing for no tasks', async () => {
    expect(await runLimited([], 4)).toEqual({ done: 0, failed: 0 })
  })
})
