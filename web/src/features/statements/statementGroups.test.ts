import { describe, expect, it } from 'vitest'
import { groupByAccount, rowsHeadline } from './statementGroups'

describe('groupByAccount', () => {
  it('puts each statement under its account and keeps the account order', () => {
    const accounts = [{ id: 'b' }, { id: 'a' }]
    const statements = [
      { bank_account: 'a', n: 1 },
      { bank_account: 'b', n: 2 },
      { bank_account: 'a', n: 3 },
    ]
    const { groups, orphans } = groupByAccount(accounts, statements)
    expect(groups.map((g) => g.account.id)).toEqual(['b', 'a'])
    expect(groups[1]!.statements.map((s) => s.n)).toEqual([1, 3])
    expect(orphans).toEqual([])
  })

  it('keeps a statement whose account is missing, and an account with none', () => {
    const { groups, orphans } = groupByAccount([{ id: 'a' }], [{ bank_account: 'zz' }])
    expect(groups[0]!.statements).toEqual([])
    expect(orphans).toEqual([{ bank_account: 'zz' }])
  })
})

describe('rowsHeadline', () => {
  it('says how many rows were read and how many still need a person', () => {
    expect(rowsHeadline(17, 12)).toBe('17 rows read, 12 still need you')
    expect(rowsHeadline(17, 1)).toBe('17 rows read, 1 still needs you')
  })
  it('says all posted when nothing waits, and nothing read when empty', () => {
    expect(rowsHeadline(17, 0)).toBe('17 rows read, all posted')
    expect(rowsHeadline(1, 0)).toBe('1 row read, all posted')
    expect(rowsHeadline(0, 0)).toBe('No rows read yet')
  })
})
