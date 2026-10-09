// What the Purchases & Sales list shows: every uploaded invoice and every booked bill as one row, however it arrived.
//
// A file that was read and booked is one row (the bill's own figures), a file still waiting for a person is one row (from what
// was read), and a bill keyed in by hand with no file is one row. Nothing here changes any data; it only lines the two lists
// up so a person sees one list and the alerts that matter on each row.

import type { Bill, InvoiceReading, LedgerAccount } from '@/api/types'

export type Tone = 'attention' | 'done' | 'neutral'

export interface ListItem {
  /** The id in the address of the page that opens it. */
  id: string
  /** Whether the page loads an uploaded invoice (``reading``) or a bill with no file (``bill``). */
  as: 'reading' | 'bill'
  kind: string
  date: string | null
  party: string
  /** A second line under the party: where it is, from the receipt. */
  detail: string
  reference: string
  paise: number | null
  documentId: string | null
  status: string
  tone: Tone
  /** Why a person should look at this row, in words. */
  alerts: string[]
  filename: string
  /** The bill and the reading this row stands for, where there is one. */
  billId: string | null
  readingId: string | null
  setAside: boolean
  createdAt: string
}

const FAILED_CHECKS = (r: InvoiceReading) => r.checks.filter((c) => !c.ok).map((c) => c.detail)

/** The alerts on an uploaded invoice that is not yet in the books. */
function readingAlerts(r: InvoiceReading): string[] {
  const alerts: string[] = []
  if (r.unreadable_reason) alerts.push(r.unreadable_reason)
  else if (r.attention) alerts.push(r.attention)
  if (r.read && !r.proved) alerts.push(...FAILED_CHECKS(r))
  if ((r.read?.unsure ?? []).length) alerts.push(`The reader was not sure of: ${r.read!.unsure.join(', ')}.`)
  const rejected = r.read?.rejected ?? []
  if (rejected.length) alerts.push(`The reader saw values it could not use: ${rejected.map((x) => x.field.replaceAll('_', ' ')).join(', ')}.`)
  return [...new Set(alerts.filter(Boolean))]
}

export function buildItems(readings: InvoiceReading[], bills: Bill[]): ListItem[] {
  const byBill = new Map(bills.map((b) => [b.id, b]))
  const claimed = new Set<string>()
  const items: ListItem[] = []

  for (const r of readings) {
    const bill = r.bill ? byBill.get(r.bill) : undefined
    if (bill) claimed.add(bill.id)
    const address = r.read?.supplier_address ?? ''
    if (bill) {
      const alerts: string[] = []
      if (r.auto_booked) alerts.push('Booked automatically from the file. Check it, and change it if anything is wrong.')
      items.push({
        id: r.id,
        as: 'reading',
        kind: bill.kind,
        date: bill.bill_date,
        party: bill.party_name,
        detail: address,
        reference: bill.reference,
        paise: bill.total_paise,
        documentId: r.document,
        status: bill.open_paise <= 0 ? 'Settled' : 'Booked',
        tone: 'done',
        alerts,
        filename: r.filename,
        billId: bill.id,
        readingId: r.id,
        setAside: false,
        createdAt: r.created_at,
      })
      continue
    }
    const setAside = r.status === 'DISCARDED'
    items.push({
      id: r.id,
      as: 'reading',
      kind: r.kind,
      date: r.read?.invoice_date ?? null,
      party: r.read?.supplier_name || r.filename || 'Invoice',
      detail: address,
      reference: r.read?.invoice_no ?? '',
      paise: r.read?.total_paise ?? null,
      documentId: r.document,
      status: setAside ? 'Set aside' : 'Needs you',
      tone: setAside ? 'neutral' : 'attention',
      alerts: setAside ? [] : readingAlerts(r),
      filename: r.filename,
      billId: null,
      readingId: r.id,
      setAside,
      createdAt: r.created_at,
    })
  }

  for (const b of bills) {
    if (claimed.has(b.id)) continue
    items.push({
      id: b.id,
      as: 'bill',
      kind: b.kind,
      date: b.bill_date,
      party: b.party_name,
      detail: '',
      reference: b.reference,
      paise: b.total_paise,
      documentId: b.document,
      status: b.open_paise <= 0 ? 'Settled' : 'Booked',
      tone: 'done',
      alerts: b.has_document ? [] : ['No invoice file is attached to this bill.'],
      filename: '',
      billId: b.id,
      readingId: null,
      setAside: false,
      createdAt: b.created_at,
    })
  }

  return items.sort((a, b) => (b.date ?? b.createdAt.slice(0, 10)).localeCompare(a.date ?? a.createdAt.slice(0, 10)) || b.createdAt.localeCompare(a.createdAt))
}

const STOP = new Set(['and', 'the', 'for', 'expense', 'expenses', 'charges', 'charge', 'other', 'misc', 'account'])
const words = (text: string) =>
  text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length >= 3 && !STOP.has(w))
    .map((w) => w.replace(/s$/, ''))

/**
 * The ledger an invoice's own description points to: the one sharing the most words with "Food and beverages" or "Office
 * rent". Only a suggestion for the form; undefined when no ledger shares a word, so the form falls back to the standard one.
 */
export function suggestLedger(hint: string, ledgers: Pick<LedgerAccount, 'id' | 'name'>[]): string | undefined {
  const wanted = new Set(words(hint))
  if (wanted.size === 0) return undefined
  let best: { id: string; score: number; length: number } | undefined
  for (const l of ledgers) {
    const score = words(l.name).filter((w) => wanted.has(w)).length
    if (score > 0 && (!best || score > best.score || (score === best.score && l.name.length < best.length))) best = { id: l.id, score, length: l.name.length }
  }
  return best?.id
}
