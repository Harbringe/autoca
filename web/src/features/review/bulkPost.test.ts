import { describe, expect, it } from 'vitest'
import type { Classification } from '@/api/types'
import { summariseBulk } from './bulkPost'

const row = (over: Record<string, unknown>, tx: Record<string, unknown> = {}) =>
  ({ review_band: 'HIGH', ledger: 'l1', is_posted: false, method: 'RULE', transaction: { is_debit: true, amount_paise: 100, ...tx }, ...over }) as unknown as Classification

describe('summariseBulk', () => {
  it('counts who placed the rows and totals each direction in paise', () => {
    const s = summariseBulk([
      row({}),
      row({ method: 'LLM' }, { amount_paise: 250 }),
      row({ method: 'REVIEWED' }, { is_debit: false, amount_paise: 1000 }),
      row({ review_band: 'ADVISED' }),
      row({ ledger: null }),
      row({ is_posted: true }),
    ])
    expect(s).toMatchObject({ count: 3, byRule: 1, byModel: 1, byPerson: 1, paidOut: 2, paidOutPaise: 350, received: 1, receivedPaise: 1000 })
  })
})
