import { describe, expect, it } from 'vitest'
import { GROUP_LABEL, LEDGER_GROUPS } from './types'

describe('the ledger groups the web knows', () => {
  it('include the sales and purchase heads a Tally import proposes, so a select shows the real group, not its first option', () => {
    expect(GROUP_LABEL.SALES).toBe('Sales Accounts')
    expect(GROUP_LABEL.PURCHASE).toBe('Purchase Accounts')
    expect(GROUP_LABEL.FIXED_ASSET).toBe('Fixed Assets')
    expect(new Set(LEDGER_GROUPS.map(([g]) => g)).size).toBe(LEDGER_GROUPS.length)
  })
})
