import { describe, expect, it } from 'vitest'
import type { Classification } from '@/api/types'
import { groupSimilar, isBulkPostable, similarTo, similarityKey } from './similarGroups'

let n = 0
const row = (over: Record<string, unknown> = {}): Classification => {
  n += 1
  const { transaction, ...rest } = over as { transaction?: Record<string, unknown> }
  return {
    id: `r${n}`,
    ledger: 'l1',
    ledger_name: 'Purchases',
    is_posted: false,
    on_party_account: false,
    method: 'LLM',
    counterparty: '',
    transaction: { narration: 'UPI/123456/ZOMATO ORDER 98', amount_paise: 10_000, is_debit: true, ...transaction },
    ...rest,
  } as unknown as Classification
}

describe('rows that are alike', () => {
  it('are the same payee where one was read, and otherwise the same narration without its numbers', () => {
    expect(similarityKey(row({ counterparty: 'Ravi  Traders' }))).toBe(similarityKey(row({ counterparty: 'RAVI TRADERS' })))
    expect(similarityKey(row({ transaction: { narration: 'UPI/111/ZOMATO ORDER 98' } }))).toBe(similarityKey(row({ transaction: { narration: 'UPI/999/ZOMATO ORDER 12' } })))
    expect(similarityKey(row({ transaction: { narration: 'UPI/111/SWIGGY' } }))).not.toBe(similarityKey(row({ transaction: { narration: 'UPI/111/ZOMATO' } })))
  })

  it('are grouped by payee, ledger and direction, the biggest group first, with what they came to', () => {
    const groups = groupSimilar([
      row({ counterparty: 'Ravi', transaction: { amount_paise: 100 } }),
      row({ counterparty: 'RAVI', transaction: { amount_paise: 250 } }),
      row({ counterparty: 'Ravi', ledger: 'l2', ledger_name: 'Repairs' }),
      row({ counterparty: 'Ravi', transaction: { is_debit: false } }),
      row({ counterparty: 'Mehta', method: 'RULE' }),
      row({ counterparty: 'Mehta', method: 'RULE' }),
      row({ counterparty: 'Mehta', method: 'RULE' }),
    ])
    expect(groups.map((g) => [g.label, g.rows.length])).toEqual([['Mehta', 3], ['Ravi', 2], ['Ravi', 1], ['Ravi', 1]])
    const ravi = groups.find((g) => g.label === 'Ravi' && g.rows.length === 2)!
    expect(ravi.totalPaise).toBe(350)
    expect(groups[0]).toMatchObject({ byRule: 3, byModel: 0, byPerson: 0 })
  })

  it('leave out what cannot be posted in bulk: no ledger, already posted, or on a party’s own account', () => {
    expect(isBulkPostable(row())).toBe(true)
    expect(isBulkPostable(row({ ledger: null }))).toBe(false)
    expect(isBulkPostable(row({ is_posted: true }))).toBe(false)
    expect(isBulkPostable(row({ on_party_account: true }))).toBe(false)
    expect(groupSimilar([row({ ledger: null }), row({ is_posted: true }), row({ on_party_account: true })])).toEqual([])
  })

  it('finds the rows like one row, itself included', () => {
    const a = row({ counterparty: 'Ravi' })
    const b = row({ counterparty: 'ravi' })
    const other = row({ counterparty: 'Mehta' })
    expect(similarTo(a, [a, b, other]).map((r) => r.id)).toEqual([a.id, b.id])
    expect(similarTo(row({ ledger: null }), [a, b])).toEqual([])
  })
})
