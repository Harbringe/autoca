// What a purchase or sales voucher comes to, worked out as it is typed.
//
// This is a PREVIEW. The server is the authority: it re-does this arithmetic, refuses what is wrong in words, and writes the
// books. The preview exists so a person sees the supplier's balance and what is wrong before they press Post, instead of
// after. It mirrors ledger/billing.py (plan_purchase, plan_sales and the notes), and src/lib/vouchers.test.ts holds the same
// figures as ledger/tests/test_billing_plan.py, so the two cannot drift without a test failing.
//
// Everything is whole paise. A rupee figure typed by a person is converted once, by parseRupees, which refuses more than two
// decimals rather than rounding them.

export type VoucherKind = 'PURCHASE' | 'SALES' | 'DEBIT_NOTE' | 'CREDIT_NOTE'

export const VOUCHER_KINDS: { value: VoucherKind; label: string; short: string }[] = [
  { value: 'PURCHASE', label: 'Purchase invoice', short: 'Purchase' },
  { value: 'SALES', label: 'Sales invoice', short: 'Sales' },
  { value: 'DEBIT_NOTE', label: 'Debit note (purchase return)', short: 'Debit note' },
  { value: 'CREDIT_NOTE', label: 'Credit note (sales return)', short: 'Credit note' },
]

export const KIND_LABEL: Record<string, string> = Object.fromEntries(VOUCHER_KINDS.map((k) => [k.value, k.label]))

/** Which parties a voucher can be booked to: a supplier for a purchase side, a customer for a sales side. */
export function isPurchaseSide(kind: VoucherKind): boolean {
  return kind === 'PURCHASE' || kind === 'DEBIT_NOTE'
}

export function rolesFor(kind: VoucherKind): string[] {
  return isPurchaseSide(kind) ? ['VENDOR', 'BOTH'] : ['CUSTOMER', 'BOTH']
}

/** The side the party's account is on: a purchase and a credit note credit it, a sale and a debit note debit it. */
export function partySide(kind: VoucherKind): 'Cr' | 'Dr' {
  return kind === 'PURCHASE' || kind === 'CREDIT_NOTE' ? 'Cr' : 'Dr'
}

/** The ledger group a new head is most likely to need, offered first when none fits. */
export function suggestedHeadGroup(kind: VoucherKind): string {
  return isPurchaseSide(kind) ? 'PURCHASE' : 'SALES'
}

/** Groups that are never an invoice's head: the money side of an invoice is the party, not a bank or the cash box. */
export const NOT_A_HEAD = new Set(['BANK', 'CASH', 'BANK_OD', 'CREDITOR', 'DEBTOR'])

export interface VoucherFigures {
  /** The taxable value of each head, in paise. */
  heads: number[]
  cgst: number
  sgst: number
  igst: number
  cess: number
  /** Signed: positive when the invoice rounds up. */
  roundOff: number
  tds: number
  rcm: boolean
}

export const NO_FIGURES: VoucherFigures = { heads: [], cgst: 0, sgst: 0, igst: 0, cess: 0, roundOff: 0, tds: 0, rcm: false }

export interface VoucherPreview {
  taxable: number
  tax: number
  /** What the party's account is debited or credited for. */
  party: number
  /** The message the server would give, when the figures cannot make a voucher. */
  error: string | null
}

export function previewVoucher(kind: VoucherKind, f: VoucherFigures): VoucherPreview {
  const taxable = f.heads.reduce((sum, h) => sum + h, 0)
  const tax = f.cgst + f.sgst + f.igst + f.cess
  const fail = (error: string): VoucherPreview => ({ taxable, tax, party: 0, error })

  if (f.heads.length === 0) return fail('An invoice needs at least one head with an amount.')
  if (f.heads.some((h) => !(h > 0))) return fail('Every head on an invoice needs an amount above zero, in whole paise.')
  if ([f.cgst, f.sgst, f.igst, f.cess].some((t) => t < 0)) return fail('Tax amounts must be zero or more.')
  if (f.igst && (f.cgst || f.sgst)) return fail('An invoice carries CGST and SGST, or IGST, not both.')
  if (f.tds < 0) return fail('TDS must be zero or more.')

  const purchase = kind === 'PURCHASE'
  if (kind === 'DEBIT_NOTE' && (f.tds || f.rcm)) return fail('A debit note does not deduct TDS or carry reverse charge in this version.')
  if ((kind === 'SALES' || kind === 'CREDIT_NOTE') && (f.tds || f.rcm)) {
    return fail('A customer’s TDS is booked when they pay, and reverse charge does not apply to our sales.')
  }

  // Purchase and debit note: the supplier is owed the taxable value plus tax (none under reverse charge) plus rounding,
  // less TDS. Sales and credit note: the customer owes taxable value plus tax plus rounding.
  const party = purchase || kind === 'DEBIT_NOTE'
    ? taxable + (f.rcm ? 0 : tax) + f.roundOff - f.tds
    : taxable + tax + f.roundOff
  if (party <= 0) {
    return fail(
      isPurchaseSide(kind)
        ? 'After tax, rounding and TDS the supplier would be owed nothing. Check the amounts.'
        : 'After tax and rounding the customer would owe nothing. Check the amounts.',
    )
  }
  return { taxable, tax, party, error: null }
}

/** The TDS sections a bill realistically triggers; the same list the server accepts (classify/treatment.py). */
export const TDS_SECTIONS: [string, string][] = [
  ['192', '192 · Salary'],
  ['194A', '194A · Interest'],
  ['194C', '194C · Contractors'],
  ['194H', '194H · Commission or brokerage'],
  ['194I', '194I · Rent'],
  ['194J', '194J · Professional or technical fees'],
  ['194Q', '194Q · Purchase of goods'],
]

/**
 * What is still owing across a list of bills, by who owes it. Payables are purchases less the debit notes that reverse
 * them; receivables are sales less their credit notes. Whole paise; a note larger than what it reverses shows as negative,
 * which is the truth (the other side owes the client).
 */
export function openPositions(rows: { kind: string; open_paise: number }[]): { payables: number; receivables: number } {
  let payables = 0
  let receivables = 0
  for (const row of rows) {
    if (row.kind === 'PURCHASE') payables += row.open_paise
    else if (row.kind === 'DEBIT_NOTE') payables -= row.open_paise
    else if (row.kind === 'SALES') receivables += row.open_paise
    else if (row.kind === 'CREDIT_NOTE') receivables -= row.open_paise
  }
  return { payables, receivables }
}
