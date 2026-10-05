import { describe, expect, it } from 'vitest'
import {
  isPurchaseSide,
  NO_FIGURES,
  openPositions,
  NOT_A_HEAD,
  partySide,
  previewVoucher,
  rolesFor,
  suggestedHeadGroup,
  type VoucherFigures,
} from './vouchers'

// The same figures as ledger/tests/test_billing_plan.py. If the server's rules change, both change, or one fails.
const f = (over: Partial<VoucherFigures>): VoucherFigures => ({ ...NO_FIGURES, heads: [10_000_000], ...over })

describe('previewVoucher mirrors the server arithmetic', () => {
  it('the Ravi Traders purchase: 1,00,000 plus 18,000 GST is 1,18,000 owed', () => {
    const p = previewVoucher('PURCHASE', f({ cgst: 900_000, sgst: 900_000 }))
    expect(p).toEqual({ taxable: 10_000_000, tax: 1_800_000, party: 11_800_000, error: null })
  })

  it('interstate tax is just tax', () => {
    expect(previewVoucher('PURCHASE', f({ igst: 1_800_000 })).party).toBe(11_800_000)
  })

  it('several heads add up', () => {
    expect(previewVoucher('PURCHASE', f({ heads: [200_000, 800_000], cgst: 90_000, sgst: 90_000 })).party).toBe(1_180_000)
  })

  it('reverse charge owes the supplier only the taxable value', () => {
    expect(previewVoucher('PURCHASE', f({ cgst: 900_000, sgst: 900_000, rcm: true })).party).toBe(10_000_000)
  })

  it('TDS is deducted at booking and the supplier is owed the net', () => {
    expect(previewVoucher('PURCHASE', f({ heads: [5_000_000], igst: 900_000, tds: 500_000 })).party).toBe(5_400_000)
  })

  it.each([
    [40, 1_000_040],
    [-40, 999_960],
  ])('rounding of %i paise moves what the party owes', (roundOff, expected) => {
    expect(previewVoucher('PURCHASE', f({ heads: [1_000_000], roundOff })).party).toBe(expected)
  })

  it('a sales invoice is what the customer owes', () => {
    expect(previewVoucher('SALES', f({ cgst: 900_000, sgst: 900_000 })).party).toBe(11_800_000)
  })

  it('a debit note is the purchase the other way round, with the same amount', () => {
    expect(previewVoucher('DEBIT_NOTE', f({ heads: [1_000_000], cgst: 90_000, sgst: 90_000 })).party).toBe(1_180_000)
  })

  it('a credit note is the sale the other way round', () => {
    expect(previewVoucher('CREDIT_NOTE', f({ heads: [1_000_000], igst: 180_000 })).party).toBe(1_180_000)
  })
})

describe('previewVoucher refuses what the server refuses', () => {
  it.each([
    ['no heads', f({ heads: [] }), 'at least one head'],
    ['a zero head', f({ heads: [0] }), 'above zero'],
    ['IGST with CGST', f({ cgst: 90, igst: 180 }), 'not both'],
    ['TDS that swallows the invoice', f({ tds: 10_000_000 }), 'owed nothing'],
    ['negative tax', f({ cgst: -1 }), 'zero or more'],
  ])('%s', (_name, figures, message) => {
    const p = previewVoucher('PURCHASE', figures)
    expect(p.error).toContain(message)
    expect(p.party).toBe(0)
  })

  it('TDS or reverse charge on a debit note, a sale or a credit note', () => {
    expect(previewVoucher('DEBIT_NOTE', f({ tds: 100 })).error).toContain('debit note')
    expect(previewVoucher('SALES', f({ tds: 100 })).error).toContain('customer')
    expect(previewVoucher('CREDIT_NOTE', f({ rcm: true })).error).toContain('customer')
  })
})

describe('which side, which party, which head', () => {
  it('a purchase and a credit note credit the party; a sale and a debit note debit it', () => {
    expect(partySide('PURCHASE')).toBe('Cr')
    expect(partySide('CREDIT_NOTE')).toBe('Cr')
    expect(partySide('SALES')).toBe('Dr')
    expect(partySide('DEBIT_NOTE')).toBe('Dr')
  })

  it('suppliers for the purchase side, customers for the sales side', () => {
    expect(isPurchaseSide('PURCHASE') && isPurchaseSide('DEBIT_NOTE')).toBe(true)
    expect(rolesFor('PURCHASE')).toEqual(['VENDOR', 'BOTH'])
    expect(rolesFor('CREDIT_NOTE')).toEqual(['CUSTOMER', 'BOTH'])
  })

  it('offers a purchase or a sales ledger first when none fits', () => {
    expect(suggestedHeadGroup('PURCHASE')).toBe('PURCHASE')
    expect(suggestedHeadGroup('SALES')).toBe('SALES')
  })

  it('a bank, cash or party account is never a head', () => {
    for (const group of ['BANK', 'CASH', 'BANK_OD', 'CREDITOR', 'DEBTOR']) expect(NOT_A_HEAD.has(group)).toBe(true)
    expect(NOT_A_HEAD.has('PURCHASE')).toBe(false)
  })
})

describe('openPositions', () => {
  it('payables are purchases less debit notes; receivables are sales less credit notes', () => {
    const rows = [
      { kind: 'PURCHASE', open_paise: 1_000_000 },
      { kind: 'PURCHASE', open_paise: 500_000 },
      { kind: 'DEBIT_NOTE', open_paise: 200_000 },
      { kind: 'SALES', open_paise: 900_000 },
      { kind: 'CREDIT_NOTE', open_paise: 100_000 },
    ]
    expect(openPositions(rows)).toEqual({ payables: 1_300_000, receivables: 800_000 })
  })

  it('an empty list owes nothing', () => {
    expect(openPositions([])).toEqual({ payables: 0, receivables: 0 })
  })
})
