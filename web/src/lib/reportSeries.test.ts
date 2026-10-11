import { describe, expect, it } from 'vitest'
import { bsPair, naturalPaise, plBridge, statementHeadlines, tbPair, tdsByMonth, topStockItems, topWithOther } from './reportSeries'

const line = (name: string, dr: number, cr: number, group = 'DIRECT_EXPENSE') => ({ name, closing_debit_paise: dr, closing_credit_paise: cr, group, ledger: null }) as never

describe('naturalPaise', () => {
  it('is positive on the natural side and negative on the other', () => {
    expect(naturalPaise({ closing_debit_paise: 500, closing_credit_paise: 0 }, 'asset')).toBe(500)
    expect(naturalPaise({ closing_debit_paise: 0, closing_credit_paise: 500 }, 'asset')).toBe(-500)
    expect(naturalPaise({ closing_debit_paise: 0, closing_credit_paise: 700 }, 'income')).toBe(700)
  })
})

describe('topWithOther', () => {
  it('keeps the biggest, folds the rest into Other (n) and drops non-positive parts', () => {
    const out = topWithOther([{ label: 'a', value: 5 }, { label: 'b', value: 9 }, { label: 'c', value: 1 }, { label: 'd', value: 2 }, { label: 'z', value: -4 }], 2)
    expect(out).toEqual([{ label: 'b', value: 9 }, { label: 'a', value: 5 }, { label: 'Other (2)', value: 3 }])
  })
  it('does not invent an Other when everything fits', () => {
    expect(topWithOther([{ label: 'a', value: 1 }], 3)).toEqual([{ label: 'a', value: 1 }])
  })
})

describe('plBridge', () => {
  const pl = { expenses: [line('Rent', 300, 0), line('Salaries', 500, 0), line('Misc', 50, 0)], total_income_paise: 1000, total_expenses_paise: 855, net_profit_paise: 145 }
  it('walks from income through the biggest heads to the result, and ends where the server says', () => {
    const steps = plBridge(pl, 2)
    expect(steps.map((s) => s.label)).toEqual(['Income', 'Salaries', 'Rent', 'Other heads (1)', 'Net profit'])
    expect(steps[1]).toMatchObject({ from: 1000, to: 500, tone: 'out' })
    // The remainder to the server's own total (855 - 800 = 55) is folded into Other so the walk ends at 145.
    expect(steps[3]).toMatchObject({ from: 200, to: 145 })
    expect(steps.at(-1)).toMatchObject({ from: 0, to: 145, tone: 'good', result: true })
  })
  it('draws a loss as a negative result with the bad tone', () => {
    const steps = plBridge({ expenses: [line('Purchases', 6800, 0)], total_income_paise: 0, total_expenses_paise: 6800, net_profit_paise: -6800 })
    expect(steps.at(-1)).toMatchObject({ label: 'Net loss', to: -6800, tone: 'bad' })
    expect(steps[1]).toMatchObject({ from: 0, to: -6800 })
  })
})

describe('bsPair and tbPair', () => {
  it('splits each side into lines and says what cannot be drawn', () => {
    const pair = bsPair({
      liabilities: [line('Capital', 0, 900), line('Overdrawn creditor', 100, 0)],
      assets: [line('Bank', 0, 300), line('Stock', 1000, 0)],
      total_assets_paise: 700,
      total_liabilities_and_profit_paise: 800,
      net_profit_paise: 0,
      balances: false,
    })
    expect(pair.left.segments.map((s) => s.value)).toEqual([900, 100])
    expect(pair.left.segments[1]!.key).toBe('opposite')
    expect(pair.left.oppositePaise).toBe(100)
    expect(pair.right.segments.map((s) => s.value)).toEqual([1000, 300])
    expect(pair.right.oppositePaise).toBe(300)
    expect(pair.gap).toBe(100)
    expect(pair.balanced).toBe(false)
  })
  it('groups trial balance rows and carries the server totals', () => {
    const pair = tbPair({
      rows: [line('Bank', 500, 0, 'BANK'), line('Cash', 100, 0, 'BANK'), line('Sales', 0, 600, 'INCOME')],
      total_debit_paise: 600,
      total_credit_paise: 600,
      balances: true,
    })
    expect(pair.left.segments).toHaveLength(1)
    expect(pair.left.segments[0]!.value).toBe(600)
    expect(pair.right.segments[0]!.value).toBe(600)
    expect(pair.gap).toBe(0)
  })
})

describe('tdsByMonth', () => {
  it('adds sections of a month together, in time order, and flags a late month', () => {
    const out = tdsByMonth([
      { year: 2026, month: 5, deducted_paise: 100, deposited_paise: 0, overdue: true },
      { year: 2026, month: 4, deducted_paise: 40, deposited_paise: 40, overdue: false },
      { year: 2026, month: 5, deducted_paise: 20, deposited_paise: 10, overdue: false },
    ])
    expect(out.map((m) => [m.key, m.deducted, m.deposited, m.late])).toEqual([
      ['2026-04', 40, 40, false],
      ['2026-05', 120, 10, true],
    ])
  })
})

describe('stock and statements', () => {
  it('ranks stock items by closing value and ignores negative stock', () => {
    expect(topStockItems([{ name: 'a', closing_value_paise: 10 }, { name: 'b', closing_value_paise: 30 }, { name: 'c', closing_value_paise: -5 }])).toEqual([{ label: 'b', value: 30 }, { label: 'a', value: 10 }])
  })
  it('takes the total lines, this year against last', () => {
    const rows = [
      { key: 'x', label: 'Heading', kind: 'heading', level: 0, note: null, current_paise: null, previous_paise: null },
      { key: 't', label: 'Total assets', kind: 'total', level: 0, note: null, current_paise: 900, previous_paise: 700 },
    ] as never
    expect(statementHeadlines(rows)).toEqual([{ key: 't', label: 'Total assets', current: 900, previous: 700 }])
  })
})
