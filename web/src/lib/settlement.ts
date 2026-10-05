// Working out what a person's settlement of a payment comes to, as they edit it.
//
// A payment on a supplier's or customer's account says nothing about which invoices it pays, so the screen asks: the
// party's open bills, each with an amount the person can set, prefilled from the server's suggestion. This turns what is
// typed into the decision the server takes, and says what is wrong with it in the server's own words. The server re-checks
// everything and is the authority; this only makes the problem visible before the button is pressed.

import { formatPaise, parseRupees } from './format'

export type Hold = 'ON_ACCOUNT' | 'ADVANCE'

export const HOLD_LABEL: Record<Hold, string> = {
  ON_ACCOUNT: 'Held on account (no invoice named)',
  ADVANCE: 'An advance (the invoice has not arrived)',
}

export interface BillRef {
  id: string
  reference: string
  open_paise: number
}

export interface Draft {
  /** What is typed against each bill, as rupees. Empty means nothing. */
  amounts: Record<string, string>
  remainder: Hold
}

export interface Decision {
  allocations: { bill: string; amount_paise: number }[]
  allocated: number
  /** What the bills do not take. Must be held on account or as an advance. */
  left: number
  remainder: Hold | null
  /** Why this cannot be posted yet, or null. */
  problem: string | null
  /** The complaint for each bill whose amount is wrong. */
  fieldErrors: Record<string, string>
}

const rupees = (paise: number) => (paise / 100).toFixed(2)

/** The server's suggestion as something typeable. */
export function draftFrom(proposal: { allocations: { bill: string; amount_paise: number }[] }): Draft {
  const amounts: Record<string, string> = {}
  for (const a of proposal.allocations) amounts[a.bill] = rupees(a.amount_paise)
  return { amounts, remainder: 'ON_ACCOUNT' }
}

export function decide(amountPaise: number, bills: BillRef[], draft: Draft): Decision {
  const allocations: Decision['allocations'] = []
  const fieldErrors: Record<string, string> = {}
  for (const bill of bills) {
    const text = (draft.amounts[bill.id] ?? '').trim()
    if (!text) continue
    const paise = parseRupees(text)
    if (paise === null || paise <= 0) {
      fieldErrors[bill.id] = 'Enter an amount in rupees, like 25,000.00.'
      continue
    }
    if (paise > bill.open_paise) {
      fieldErrors[bill.id] = `Only ${formatPaise(bill.open_paise)} of this bill is still open.`
      continue
    }
    allocations.push({ bill: bill.id, amount_paise: paise })
  }

  const allocated = allocations.reduce((sum, a) => sum + a.amount_paise, 0)
  const left = amountPaise - allocated
  let problem: string | null = null
  if (Object.keys(fieldErrors).length) problem = 'Fix the amounts marked below.'
  else if (left < 0) problem = `The bills add up to ${formatPaise(allocated)}, more than the ${formatPaise(amountPaise)} that moved.`
  return { allocations, allocated, left: Math.max(left, 0), remainder: left > 0 ? draft.remainder : null, problem, fieldErrors }
}

/** How sure the suggestion is, in a sentence. It is always only a suggestion. */
export function basisNote(basis: string, references: string[]): string {
  if (basis === 'exact_one') return `This is exactly ${references[0] ?? 'one bill'}.`
  if (basis === 'exact_set') return `These ${references.length} bills add up to exactly this payment.`
  if (basis === 'oldest_first') return 'No bill matches exactly, so it is applied to the oldest bills first.'
  return 'There is nothing open to settle, so hold it on account or as an advance.'
}
