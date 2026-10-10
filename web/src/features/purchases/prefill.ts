// The starting values of the voucher form, from what was read off an uploaded invoice or from a bill already booked.
// Nothing is booked from here: the person sees every field, changes what is wrong, and presses Save.

import type { BillDetail, InvoiceReading } from '@/api/types'
import type { ReceiptFacts, VoucherPrefill } from '@/features/bills/VoucherDialog'
import { normaliseName } from '@/lib/names'

type Read = NonNullable<InvoiceReading['read']>

const factsOf = (read: Read): ReceiptFacts => ({
  seller: { name: read.supplier_name, gstin: read.supplier_gstin ?? '', address: read.supplier_address, pan: read.supplier_pan },
  buyer: { name: read.buyer_name, gstin: read.buyer_gstin ?? '', address: read.buyer_address },
  kindReason: read.kind_reason ?? '',
  ownGstinGuess: read.own_gstin_guess ?? '',
  address: read.supplier_address,
  pan: read.supplier_pan,
  place: read.place_of_supply,
  terms: read.payment_terms,
  paymentMode: read.payment_mode,
  currency: read.currency,
  category: read.expense_hint,
  unsure: read.unsure ?? [],
  details: read.details ?? {},
  rejected: read.rejected ?? [],
  tcsPaise: read.tcs_paise ?? 0,
  otherChargesPaise: read.other_charges_paise ?? 0,
  discountPaise: read.discount_paise ?? null,
})

/** What the receipt adds beyond the voucher's own fields: the due date, its lines, and the facts shown beside the form. */
function extrasOf(read: Read | null | undefined): Pick<VoucherPrefill, 'dueDate' | 'items' | 'facts'> {
  return read ? { dueDate: read.due_date, items: read.items ?? [], facts: factsOf(read) } : {}
}

/** The form for an uploaded invoice that is not booked yet. ``headLedger`` is the ledger its taxable value goes to. */
export function prefillFromReading(reading: InvoiceReading, headLedger?: string): VoucherPrefill | null {
  const read = reading.read
  if (!read) return null
  // The file's own kind, else what the names suggested; with neither, the person chooses (never a silent purchase).
  const decided = reading.kind === 'SALES' || reading.kind === 'PURCHASE' ? reading.kind : read.suggested_kind
  const unsure = decided !== 'SALES' && decided !== 'PURCHASE'
  const purchase = decided !== 'SALES'
  const counterparty = unsure ? '' : purchase ? read.supplier_name : read.buyer_name
  return {
    kind: purchase ? 'PURCHASE' : 'SALES',
    kindUnsure: unsure,
    partyId: reading.suggested_party?.id,
    newParty: reading.suggested_party || !counterparty ? undefined : { name: normaliseName(counterparty), gstin: read.counterparty_gstin || (purchase ? read.supplier_gstin : read.buyer_gstin) || '' },
    reference: read.invoice_no,
    billDate: read.invoice_date,
    taxablePaise: read.taxable_paise,
    cgstPaise: read.cgst_paise,
    sgstPaise: read.sgst_paise,
    igstPaise: read.igst_paise,
    cessPaise: read.cess_paise,
    roundOffPaise: read.round_off_paise,
    document: reading.document,
    headLedger,
    ...extrasOf(read),
  }
}

/** A booked bill as a form to change: its figures, and the ledger its taxable value went to. */
export function prefillOfBill(bill: BillDetail, document: string | undefined, reading?: InvoiceReading): VoucherPrefill {
  const side = bill.kind === 'PURCHASE' ? 'DR' : 'CR'
  const head = bill.lines.find((l) => !l.party && l.direction === side && l.amount_paise === bill.taxable_paise)
  return {
    kind: bill.kind as VoucherPrefill['kind'],
    partyId: bill.party,
    reference: bill.reference,
    billDate: bill.bill_date,
    taxablePaise: bill.taxable_paise,
    cgstPaise: bill.cgst_paise,
    sgstPaise: bill.sgst_paise,
    igstPaise: bill.igst_paise,
    cessPaise: bill.cess_paise,
    roundOffPaise: bill.round_off_paise,
    document,
    reviseBill: bill.id,
    headLedger: head?.ledger_account,
    ...extrasOf(reading?.read),
    dueDate: bill.due_date,
  }
}

/** A blank form for a bill keyed in by hand. */
export function blankPrefill(kind: VoucherPrefill['kind'], headLedger?: string): VoucherPrefill {
  return { kind, reference: '', cgstPaise: 0, sgstPaise: 0, igstPaise: 0, cessPaise: 0, roundOffPaise: 0, headLedger }
}
