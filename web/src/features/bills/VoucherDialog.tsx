// Booking a purchase or sales voucher: who it is with, what it is for, the tax as printed, and what the party's account
// will be left at.
//
// The figures at the bottom are a preview worked out as you type (src/lib/vouchers.ts). The server re-does the
// arithmetic and is the authority: what it refuses, it says in words, and those words are shown as they are. So the
// preview can only ever be early, never different.

import { useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowRight, Plus, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import { ledgers as ledgersQuery, parties as partiesQuery } from '@/api/queries/books'
import { usePostBill, useReviseBill } from '@/api/queries/bills'
import { clientDetail, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BillCreateRequest, InvoiceReading, Party } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { Button } from '@/components/ui/button'
import { Checkbox, Select } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { LedgerPicker, usableLedgers } from '@/features/review/LedgerPicker'
import { formatDate, formatPaise, parseDate, parseRupees } from '@/lib/format'
import { normaliseName, sameBusiness, sharesAWord } from '@/lib/names'
import { cn } from '@/lib/utils'
import {
  isPurchaseSide,
  NOT_A_HEAD,
  partySide,
  previewVoucher,
  rolesFor,
  suggestedHeadGroup,
  TDS_SECTIONS,
  VOUCHER_KINDS,
  type VoucherKind,
} from '@/lib/vouchers'

interface Head {
  key: number
  ledger: string | null
  amount: string
  /** What the line was on the invoice, when it came from one. */
  description?: string
}

type ReadItem = NonNullable<InvoiceReading['read']>['items'][number]

/** What a receipt says that the voucher has no field for, shown beside the form so the person can see what was read. */
/** One side of the invoice, as printed. */
export interface PartyFacts {
  name: string
  gstin: string
  address: string
  pan?: string
}

export interface ReceiptFacts {
  /** Who issued it and who is billed. Both are shown, whichever kind the voucher is. */
  seller?: PartyFacts
  buyer?: PartyFacts
  /** Why the kind was suggested, when only the names could say. */
  kindReason?: string
  /** The GSTIN on the client's side of the invoice, to add under GST. */
  ownGstinGuess?: string
  address: string
  pan: string
  place: string
  terms: string
  paymentMode: string
  currency: string
  category: string
  unsure: string[]
  /** Other facts printed on the document (type, IRN, e-way bill, PO number, bank details, ...), only those found. */
  details?: Record<string, string>
  /** Values the reader saw but could not use, with why, so a blank field is not a mystery. */
  rejected?: { field: string; value: string; why: string }[]
  tcsPaise?: number
  otherChargesPaise?: number
  discountPaise?: number | null
}

const DETAIL_LABELS: [string, string][] = [
  ['document_type', 'Document'], ['po_number', 'PO number'], ['po_date', 'PO date'], ['eway_bill_no', 'E-way bill'],
  ['vehicle_no', 'Vehicle'], ['irn', 'IRN'], ['ack_no', 'Ack no.'], ['ack_date', 'Ack date'], ['ship_to_name', 'Ship to'],
  ['ship_to_address', 'Ship-to address'], ['buyer_pan', 'Buyer PAN'], ['supplier_email', 'Seller email'], ['supplier_phone', 'Seller phone'],
  ['bank_name', 'Seller bank'], ['bank_account_no', 'Account no.'], ['bank_ifsc', 'IFSC'], ['reverse_charge', 'Reverse charge'],
  ['amount_in_words', 'In words'], ['notes', 'Notes'],
]

/** A fact as a person reads it: `tax_invoice` is "Tax invoice", `yes` is "Yes". */
function factValue(key: string, value: string): string {
  if (key === 'document_type') return value.charAt(0).toUpperCase() + value.slice(1).replaceAll('_', ' ')
  if (key === 'reverse_charge') return value === 'yes' ? 'Yes' : 'No'
  return value
}

const FIELD_NAMES: Record<string, string> = {
  supplier_gstin: 'Supplier GSTIN', buyer_gstin: 'Buyer GSTIN', supplier_pan: 'Supplier PAN', buyer_pan: 'Buyer PAN',
  invoice_date: 'Invoice date', due_date: 'Due date', payment_mode: 'Payment mode', currency: 'Currency',
  document_type: 'Document type', ack_date: 'Ack date', po_date: 'PO date', bank_ifsc: 'IFSC',
}

/** How many of the facts printed on a receipt are listed at once; the rest fold under one line. */
const FACTS_SHOWN = 4

const PAYMENT_MODE: Record<string, string> = { cash: 'Cash', card: 'Card', upi: 'UPI', bank_transfer: 'Bank transfer', cheque: 'Cheque', credit: 'On credit (not yet paid)' }

const NEW_PARTY = '__new__'

/** The client's party this invoice names, if exactly one fits: the same GSTIN, else the same name, else the same business. */
function findParty(parties: Party[], name: string, gstin: string): Party | undefined {
  const wanted = normaliseName(name).toLowerCase()
  const byGstin = gstin ? parties.filter((p) => (p.gstin ?? '').toUpperCase() === gstin.toUpperCase()) : []
  if (byGstin.length === 1) return byGstin[0]
  if (!wanted) return undefined
  const byName = parties.filter((p) => normaliseName(p.canonical_name).toLowerCase() === wanted)
  if (byName.length === 1) return byName[0]
  const alike = parties.filter((p) => sameBusiness(p.canonical_name, name))
  return alike.length === 1 ? alike[0] : undefined
}

/** What an uploaded invoice was read as, to start the form from. The person still confirms every field. */
export interface VoucherPrefill {
  kind: VoucherKind
  /** Neither the GSTINs nor the names say whether this is a purchase or a sale: the person must choose. */
  kindUnsure?: boolean
  /** The GSTIN printed on the client's own side of the invoice, to start the form with. */
  ownGstin?: string
  /** A narration worked out from what was read; the person may change it. */
  narration?: string
  partyId?: string
  newParty?: { name: string; gstin: string }
  reference: string
  /** ISO date. */
  billDate?: string | null
  taxablePaise?: number | null
  cgstPaise: number
  sgstPaise: number
  igstPaise: number
  cessPaise: number
  roundOffPaise: number
  /** The stored invoice file this voucher is being booked from, so it is attached and its reading closed. */
  document?: string
  /** Set to change a bill already booked: the form starts from it and saving replaces it. */
  reviseBill?: string
  /** The ledger the taxable value went to, when changing a booked bill. */
  headLedger?: string
  /** ISO date the invoice says payment is due. */
  dueDate?: string | null
  /** The lines the invoice listed, for the Itemizations tab. */
  items?: ReadItem[]
  facts?: ReceiptFacts
}

const asRupees = (paise: number | null | undefined) => (paise ? (paise / 100).toFixed(2) : '')
let nextKey = 1
const blankHead = (): Head => ({ key: nextKey++, ledger: null, amount: '' })

/** A typed rupee amount: empty is zero, anything that is not an amount is flagged rather than guessed. */
function amountOf(text: string): { paise: number; ok: boolean } {
  if (!text.trim()) return { paise: 0, ok: true }
  const paise = parseRupees(text)
  return paise === null ? { paise: 0, ok: false } : { paise, ok: true }
}

/** The voucher's fields and the booking of it, with no frame of its own: a dialog, or half of the invoice capture screen. */
export function VoucherForm({
  clientId,
  onClose,
  initialKind = 'PURCHASE',
  prefill,
  layout = 'dialog',
  formId,
  onReadAgain,
  readingAgain,
  tab: tabProp,
  onTabChange,
}: {
  clientId: string
  /** Called after it is booked, and by Cancel. */
  onClose: () => void
  initialKind?: VoucherKind
  prefill?: VoucherPrefill
  /** ``page``: tabs for Details and Itemizations, and no buttons of its own (the page's Save button submits it by ``formId``). */
  layout?: 'dialog' | 'page'
  /** Offered where no lines were read: read the stored file again with the current reader. */
  onReadAgain?: () => void
  readingAgain?: boolean
  /** Kept by the page, so reading the file again (which restarts the form) leaves the person on the tab they were on. */
  tab?: 'details' | 'items'
  onTabChange?: (tab: 'details' | 'items') => void
  formId?: string
}) {
  const parties = useQuery(partiesQuery(clientId))
  const ledgers = useQuery(ledgersQuery(clientId))
  const post = usePostBill(clientId)
  const revise = useReviseBill(clientId)
  const invalidate = useInvalidateClient(clientId)

  const [kind, setKind] = useState<VoucherKind>(prefill?.kind ?? initialKind)
  const [kindChosen, setKindChosen] = useState(!prefill?.kindUnsure)
  const [partyId, setPartyId] = useState(prefill?.partyId ?? '')
  const [reference, setReference] = useState(prefill?.reference ?? '')
  const [billDate, setBillDate] = useState(() => formatDate(prefill?.billDate ?? new Date().toISOString().slice(0, 10)))
  const [dueDate, setDueDate] = useState(prefill?.dueDate ? formatDate(prefill.dueDate) : '')
  const [ownTab, setOwnTab] = useState<'details' | 'items'>('details')
  const tab = tabProp ?? ownTab
  const setTab = onTabChange ?? setOwnTab
  const [heads, setHeads] = useState<Head[]>(() => [{ ...blankHead(), ledger: prefill?.headLedger ?? null, amount: asRupees(prefill?.taxablePaise) }])
  const [tax, setTax] = useState({
    cgst: asRupees(prefill?.cgstPaise),
    sgst: asRupees(prefill?.sgstPaise),
    igst: asRupees(prefill?.igstPaise),
    cess: asRupees(prefill?.cessPaise),
  })
  const [roundOff, setRoundOff] = useState(prefill?.roundOffPaise ? (prefill.roundOffPaise / 100).toFixed(2) : '')
  const [tds, setTds] = useState('')
  const [tdsSection, setTdsSection] = useState('')
  const [rcm, setRcm] = useState(false)
  const [narration, setNarration] = useState(prefill?.narration ?? '')
  const [paidFrom, setPaidFrom] = useState('')
  const [ownGstin, setOwnGstin] = useState(prefill?.ownGstin ?? '')
  const [matchedNote, setMatchedNote] = useState('')
  const clientQuery = useQuery(clientDetail(clientId))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [newParty, setNewParty] = useState<{ name: string; gstin: string } | null>(prefill?.newParty ?? null)
  const [saving, setSaving] = useState(false)

  const purchaseSide = isPurchaseSide(kind)
  const canTds = kind === 'PURCHASE'
  const canRcm = kind === 'PURCHASE'
  // The invoice's lines, editable here: what is left is kept with the invoice so the party's next one is filled the same way.
  const [items, setItems] = useState<ReadItem[]>(() => prefill?.items ?? [])
  function editLine(n: number, patch: Partial<ReadItem>) {
    setItems((current) => current.map((line, i) => (i === n ? { ...line, ...patch } : line)))
  }
  const itemsSum = items.reduce((sum, i) => sum + (i.amount_paise ?? 0), 0)
  // The printed lines can stand in for the ledger lines only when they add up to the taxable value the form already has.
  const itemsTie = items.length > 1 && items.every((i) => i.amount_paise != null) && itemsSum === (prefill?.taxablePaise ?? -1)

  const suitable = useMemo(
    () =>
      (parties.data ?? [])
        .filter((p) => p.is_active && rolesFor(kind).includes(p.role as string))
        .sort((a, b) => a.canonical_name.localeCompare(b.canonical_name)),
    [parties.data, kind],
  )
  const headLedgers = useMemo(() => usableLedgers(ledgers.data).filter((l) => !NOT_A_HEAD.has(l.group ?? '')), [ledgers.data])

  const amounts = {
    heads: heads.map((h) => amountOf(h.amount)),
    cgst: amountOf(tax.cgst),
    sgst: amountOf(tax.sgst),
    igst: amountOf(tax.igst),
    cess: amountOf(tax.cess),
    roundOff: amountOf(roundOff),
    tds: amountOf(tds),
  }
  const unreadable = [...amounts.heads, amounts.cgst, amounts.sgst, amounts.igst, amounts.cess, amounts.roundOff, amounts.tds].some((a) => !a.ok)
  // Only the lines something has been typed on, so an empty form shows no complaint.
  const typedHeads = amounts.heads.map((a) => a.paise).filter((_, i) => (heads[i]?.amount.trim() ?? '') !== '')
  const preview = previewVoucher(kind, {
    heads: typedHeads,
    cgst: amounts.cgst.paise,
    sgst: amounts.sgst.paise,
    igst: amounts.igst.paise,
    cess: amounts.cess.paise,
    roundOff: amounts.roundOff.paise,
    tds: canTds ? amounts.tds.paise : 0,
    rcm: canRcm && rcm,
  })
  const anythingTyped = typedHeads.length > 0

  function changeKind(next: VoucherKind) {
    setKind(next)
    setKindChosen(true)
    setPartyId('')
    setRcm(false)
    setTds('')
    setTdsSection('')
    setNewParty(null)
    setMatchedNote('')
    setErrors({})
    // The invoice says who is on its other side; now the type is known, start the party from that.
    const facts = isPurchaseSide(next) ? prefill?.facts?.seller : prefill?.facts?.buyer
    if (facts?.name || facts?.gstin) {
      const found = findParty((parties.data ?? []).filter((p) => p.is_active && rolesFor(next).includes(p.role as string)), facts.name, facts.gstin)
      if (found) {
        setPartyId(found.id)
        setMatchedNote(`Matched to ${normaliseName(found.canonical_name)}, already on file.`)
      } else if (facts.name) {
        setNewParty({ name: normaliseName(facts.name), gstin: facts.gstin })
      }
    }
  }

  /** The round off that brings taxable value plus tax to the nearest whole rupee (the way a printed invoice rounds). */
  function roundToRupee() {
    const before = amounts.heads.reduce((sum, h) => sum + h.paise, 0) + amounts.cgst.paise + amounts.sgst.paise + amounts.igst.paise + amounts.cess.paise
    const nearest = Math.round(before / 100) * 100
    const diff = nearest - before
    setRoundOff(diff === 0 ? '' : (diff / 100).toFixed(2))
  }

  function splitByLines() {
    const ledger = heads[0]?.ledger ?? null
    setHeads(items.map((i) => ({ ...blankHead(), ledger, amount: asRupees(i.amount_paise), description: i.description })))
    setTab('details')
  }

  function reset() {
    setPartyId('')
    setReference('')
    setDueDate('')
    setHeads([blankHead()])
    setTax({ cgst: '', sgst: '', igst: '', cess: '' })
    setRoundOff('')
    setTds('')
    setTdsSection('')
    setRcm(false)
    setNarration('')
    setOwnGstin('')
    setErrors({})
    setNewParty(null)
  }

  async function createParty() {
    if (!newParty) return
    try {
      const made = await raw.post<Party>(`${V1}/clients/${clientId}/parties/`, {
        canonical_name: newParty.name.trim(),
        role: purchaseSide ? 'VENDOR' : 'CUSTOMER',
        gstin: newParty.gstin.trim().toUpperCase(),
      })
      await invalidate()
      setPartyId(made.id)
      setNewParty(null)
      toast.success(`${made.canonical_name} added`)
    } catch (e) {
      const next: Record<string, string> = {}
      if (isApiError(e) && Object.keys(e.fields).length) {
        for (const [name, messages] of Object.entries(e.fields)) next[name === 'canonical_name' ? 'newPartyName' : name === 'gstin' ? 'newPartyGstin' : name] = messages[0] ?? ''
      } else next.root = messageOf(e)
      setErrors((current) => ({ ...current, ...next }))
    }
  }

  async function submit() {
    const found: Record<string, string> = {}
    const iso = parseDate(billDate)
    const due = dueDate.trim() ? parseDate(dueDate) : null
    if (!kindChosen) found.kind = 'Say whether this is a purchase or a sale.'
    if (!partyId) found.party = purchaseSide ? 'Choose the supplier.' : 'Choose the customer.'
    if (!reference.trim()) found.reference = 'Enter the invoice number as printed.'
    if (!iso) found.bill_date = 'Enter a date as DD-MM-YYYY, for example 01-10-2025.'
    if (dueDate.trim() && !due) found.due_date = 'Enter a date as DD-MM-YYYY.'
    heads.forEach((h, i) => {
      if (!h.ledger) found[`head-${h.key}-ledger`] = 'Choose where this goes.'
      if (!amounts.heads[i]?.ok || !h.amount.trim()) found[`head-${h.key}-amount`] = 'Enter the taxable value, like 10,000.00.'
    })
    if (unreadable) found.root = 'One of the amounts is not a number. Use rupees and at most two decimals, like 1,18,000.50.'
    if (!Object.keys(found).length && preview.error) found.root = preview.error
    setErrors(found)
    if (Object.keys(found).length) return

    const body: BillCreateRequest = {
      kind,
      party: partyId,
      reference: reference.trim(),
      bill_date: iso!,
      due_date: due,
      heads: heads.map((h, i) => ({ ledger: h.ledger!, amount_paise: amounts.heads[i]?.paise ?? 0 })),
      cgst_paise: amounts.cgst.paise,
      sgst_paise: amounts.sgst.paise,
      igst_paise: amounts.igst.paise,
      cess_paise: amounts.cess.paise,
      round_off_paise: amounts.roundOff.paise,
      tds_paise: canTds ? amounts.tds.paise : 0,
      tds_section: (canTds ? tdsSection : '') as BillCreateRequest['tds_section'],
      rcm: canRcm && rcm,
      narration: narration.trim() || heads.map((h) => h.description?.trim()).filter(Boolean).join('; ').slice(0, 200),
      own_gstin: ownGstin.trim().toUpperCase(),
      items: items
        .filter((i) => i.description.trim())
        .map((i) => ({
          description: i.description.trim().slice(0, 200),
          read_description: (i.read_description ?? '').slice(0, 200),
          hsn_sac: (i.hsn_sac ?? '').replace(/\D/g, '').slice(0, 8),
          quantity: (i.quantity ?? '').slice(0, 20),
          unit: (i.unit ?? '').slice(0, 16),
          rate_paise: i.rate_paise ?? null,
          amount_paise: i.amount_paise ?? null,
          gst_rate: i.gst_rate ?? null,
        })),
      document: prefill?.document ?? null,
      paid_from: !prefill?.reviseBill && paidFrom && (kind === 'PURCHASE' || kind === 'SALES') ? paidFrom : null,
    }
    setSaving(true)
    try {
      const made = prefill?.reviseBill
        ? await revise.mutateAsync({ id: prefill.reviseBill, body })
        : await post.mutateAsync(body)
      toast.success(`${made.voucher_type} No. ${made.entry_no} ${prefill?.reviseBill ? 'changed' : 'booked'} · ${made.reference}`)
      reset()
      onClose()
    } catch (e) {
      const next: Record<string, string> = {}
      if (isApiError(e) && Object.keys(e.fields).length) {
        for (const [name, messages] of Object.entries(e.fields)) next[name] = messages[0] ?? ''
        next.root ??= 'The server did not accept some of the fields; see below.'
      } else next.root = messageOf(e)
      setErrors(next)
    } finally {
      setSaving(false)
    }
  }

  const partyLabel = purchaseSide ? 'Supplier' : 'Customer'

  // One side of the invoice is the client; the other is the party. A purchase reads From (the supplier) To (the client); a sale
  // reads From (the client) To (the customer).
  const counterFacts = purchaseSide ? prefill?.facts?.seller : prefill?.facts?.buyer
  const ownFacts = purchaseSide ? prefill?.facts?.buyer : prefill?.facts?.seller
  const clientName = normaliseName(clientQuery.data?.name ?? '')
  const counterpartyCard = (
    <fieldset className="grid min-w-0 gap-2 rounded-md border bg-card p-3">
      <legend className="px-1 text-xs font-medium text-muted-foreground">{purchaseSide ? 'From · seller' : 'To · buyer'}</legend>
      <Field label={partyLabel} error={errors.party}>
        {(props) => (
          <Select
            {...props}
            value={newParty ? NEW_PARTY : partyId}
            onChange={(e) => {
              setMatchedNote('')
              if (e.target.value === NEW_PARTY) {
                setNewParty({ name: counterFacts?.name ? normaliseName(counterFacts.name) : '', gstin: counterFacts?.gstin ?? '' })
                setPartyId('')
              } else {
                setNewParty(null)
                setPartyId(e.target.value)
              }
            }}
          >
            <option value="">Choose…</option>
            {suitable.map((p) => (
              <option key={p.id} value={p.id}>{normaliseName(p.canonical_name)}</option>
            ))}
            <option value={NEW_PARTY}>+ Add a new {partyLabel.toLowerCase()}…</option>
          </Select>
        )}
      </Field>
      {matchedNote && <p className="text-xs text-success">{matchedNote}</p>}
      {newParty && (
        <div className="grid gap-2 rounded-md border border-dashed p-2">
          <Field label="Name" error={errors.newPartyName}>
            {(props) => <Input {...props} autoFocus value={newParty.name} onChange={(e) => setNewParty({ ...newParty, name: e.target.value })} />}
          </Field>
          <Field label="GSTIN (blank if unregistered)" error={errors.newPartyGstin} mask="gstin">
            {(props, m) => <Input {...props} {...m} value={newParty.gstin} onChange={(e) => setNewParty({ ...newParty, gstin: e.target.value })} />}
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setNewParty(null)}>Cancel</Button>
            <Button type="button" size="sm" disabled={!newParty.name.trim()} onClick={() => void createParty()}>
              Add {partyLabel.toLowerCase()}
            </Button>
          </div>
        </div>
      )}
      <PrintedLines label="Printed on the invoice" party={counterFacts} />
    </fieldset>
  )
  const ownCard = (
    <fieldset className="grid min-w-0 gap-2 rounded-md border bg-card p-3">
      <legend className="px-1 text-xs font-medium text-muted-foreground">{purchaseSide ? 'To · buyer' : 'From · seller'}</legend>
      <div className="font-medium text-heading">{clientName || 'This client'}</div>
      <Field label="GSTIN on this invoice" hint="Filled from the invoice; only needed if the client has more than one" error={errors.own_gstin} mask="gstin">
        {(props, m) => <Input {...props} {...m} value={ownGstin} onChange={(e) => setOwnGstin(e.target.value)} />}
      </Field>
      {ownFacts?.name && clientName && !sharesAWord(ownFacts.name, clientName) && (
        <p role="status" className="rounded-sm bg-accent px-2 py-1 text-xs text-warning">
          This invoice is made out to “{normaliseName(ownFacts.name)}”, not to {clientName}. Check it is the right client’s invoice.
        </p>
      )}
      <PrintedLines label="Printed on the invoice" party={ownFacts ? { ...ownFacts, name: '', gstin: '' } : undefined} />
    </fieldset>
  )

  // A new party named on the invoice that the client already has under the same business name is that party: select it
  // instead of offering to add a second one. Once, when the parties arrive; after that the person is in charge.
  const autoMatched = useRef(false)
  useEffect(() => {
    if (autoMatched.current || !parties.data || partyId || !newParty?.name.trim()) return
    autoMatched.current = true
    const found = findParty(suitable, newParty.name, newParty.gstin)
    if (found) {
      setPartyId(found.id)
      setNewParty(null)
      setMatchedNote(`Matched to ${normaliseName(found.canonical_name)}, already on file.`)
    }
  }, [parties.data, suitable, partyId, newParty])

  return (
    <form
      id={formId}
      className="grid gap-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      {layout === 'page' && (
        <div role="tablist" aria-label="Sections of the form" className="no-print flex gap-5 border-b">
          {(['details', 'items'] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={cn('-mb-px border-b-2 px-0.5 pb-2 text-sm font-medium', tab === id ? 'border-primary text-heading' : 'border-transparent text-muted-foreground hover:text-foreground')}
            >
              {id === 'details' ? 'Details' : `Itemizations${items.length ? ` (${items.length})` : ''}`}
            </button>
          ))}
        </div>
      )}

      {layout === 'page' && tab === 'items' && (
        <section aria-label="Itemizations" className="grid gap-3">
          {items.length === 0 ? (
            <div className="grid justify-items-start gap-2 rounded-md border border-dashed p-4 text-sm">
              <p className="text-muted-foreground">
                No lines were read from this invoice. The whole taxable value goes to the ledger on the Details tab; add more lines there to split it.
              </p>
              {onReadAgain && (
                <>
                  <Button type="button" variant="outline" size="sm" onClick={onReadAgain} disabled={readingAgain}>
                    {readingAgain ? 'Reading…' : 'Read the lines again'}
                  </Button>
                  <p className="text-xs text-muted-foreground">Reads the stored file again with the current reader. Nothing you have typed on this page is kept.</p>
                </>
              )}
            </div>
          ) : (
            <>
              <ol aria-label="Lines as printed on the invoice" className="grid gap-3">
                {items.map((i, n) => (
                  <li key={n} className="grid gap-2 rounded-md border bg-card p-3">
                    <div className="flex items-start gap-2">
                      <span className="mt-2 w-5 shrink-0 text-center text-xs font-medium text-muted-foreground" aria-hidden>{n + 1}</span>
                      <div className="min-w-0 flex-1">
                        <Input
                          aria-label={`Description of line ${n + 1}`}
                          value={i.description}
                          onChange={(e) => editLine(n, { description: e.target.value })}
                        />
                        {i.remembered && i.read_description && i.read_description !== i.description && (
                          <div className="mt-0.5 text-xs text-muted-foreground" title={i.read_description}>
                            Remembered wording; the invoice printed “{i.read_description.slice(0, 48)}{i.read_description.length > 48 ? '…' : ''}”
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2 pl-7 sm:grid-cols-6">
                      <label className="grid gap-0.5 text-xs text-muted-foreground">
                        HSN/SAC
                        <Input aria-label={`HSN/SAC of line ${n + 1}`} value={i.hsn_sac} onChange={(e) => editLine(n, { hsn_sac: e.target.value })} />
                      </label>
                      <label className="grid gap-0.5 text-xs text-muted-foreground">
                        Quantity
                        <Input aria-label={`Quantity of line ${n + 1}`} inputMode="decimal" className="num text-right" value={i.quantity} onChange={(e) => editLine(n, { quantity: e.target.value })} />
                        {i.usual_quantity && i.usual_quantity !== i.quantity && (
                          <button type="button" className="text-left text-xs text-primary underline" onClick={() => editLine(n, { quantity: i.usual_quantity ?? '' })}>
                            Usually {i.usual_quantity}
                          </button>
                        )}
                      </label>
                      <label className="grid gap-0.5 text-xs text-muted-foreground">
                        Unit
                        <Input aria-label={`Unit of line ${n + 1}`} value={i.unit} onChange={(e) => editLine(n, { unit: e.target.value })} />
                      </label>
                      <label className="grid gap-0.5 text-xs text-muted-foreground">
                        Rate (₹)
                        <Input
                          aria-label={`Rate of line ${n + 1}`}
                          inputMode="decimal"
                          className="num text-right"
                          defaultValue={i.rate_paise != null ? (i.rate_paise / 100).toFixed(2) : ''}
                          onBlur={(e) => editLine(n, { rate_paise: e.target.value.trim() ? parseRupees(e.target.value) : null })}
                        />
                      </label>
                      <label className="grid gap-0.5 text-xs text-muted-foreground">
                        Amount (₹)
                        <Input
                          aria-label={`Amount of line ${n + 1}`}
                          inputMode="decimal"
                          className="num text-right"
                          defaultValue={i.amount_paise != null ? (i.amount_paise / 100).toFixed(2) : ''}
                          onBlur={(e) => editLine(n, { amount_paise: e.target.value.trim() ? parseRupees(e.target.value) : null })}
                        />
                      </label>
                      <div className="grid gap-0.5 text-xs text-muted-foreground" title={i.gst_rate_derived ? 'Worked out from the tax amounts; not printed on the line' : undefined}>
                        GST %
                        <div className="num flex h-10 items-center justify-end px-1 text-sm text-foreground">
                          {i.gst_rate != null ? `${i.gst_rate}${i.gst_rate_derived ? '*' : ''}` : '—'}
                        </div>
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              <div className="flex justify-between border-t pt-2 text-sm font-medium">
                <span>Lines total</span>
                <span className="num">₹{(itemsSum / 100).toFixed(2)}</span>
              </div>
              {itemsTie ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-accent-edge bg-accent p-2 text-sm">
                  <span>These lines add up to the taxable value. Give each its own ledger?</span>
                  <Button type="button" size="sm" variant="outline" onClick={splitByLines}>Use one line per item</Button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {items.some((i) => i.amount_paise == null) ? 'Some lines have no amount' : `The lines add up to ₹${(itemsSum / 100).toFixed(2)}, not the taxable value`}, so they are shown for reference only.
                </p>
              )}
            </>
          )}
        </section>
      )}

      <div className={layout === 'page' && tab !== 'details' ? 'hidden' : 'grid gap-4'}>
      {prefill?.facts && <ReceiptFactsCard facts={prefill.facts} />}
      <div className="@container grid gap-4">
        <section aria-label="From and to" className="grid gap-2 @lg:grid-cols-[1fr_auto_1fr] @lg:items-stretch">
          {purchaseSide ? (
            <>
              {counterpartyCard}
              <Connector />
              {ownCard}
            </>
          ) : (
            <>
              {ownCard}
              <Connector />
              {counterpartyCard}
            </>
          )}
        </section>

        <div className="grid gap-4 @sm:grid-cols-2">
          <Field label="Voucher type" error={errors.kind}>
            {(props) => (
              <Select {...props} value={kindChosen ? kind : ''} onChange={(e) => changeKind(e.target.value as VoucherKind)}>
                {!kindChosen && <option value="" disabled>Choose purchase or sale…</option>}
                {VOUCHER_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>{k.label}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Invoice number" error={errors.reference} hint="As printed on the document">
            {(props) => <Input {...props} autoComplete="off" title="The same number from the same party is refused as a duplicate." value={reference} onChange={(e) => setReference(e.target.value)} />}
          </Field>
          <Field label="Invoice date" error={errors.bill_date}>
            {(props) => <DateInput {...props} value={billDate} onChange={(e) => setBillDate(e.target.value)} />}
          </Field>
          <Field label="Due date (optional)" error={errors.due_date}>
            {(props) => <DateInput {...props} value={dueDate} onChange={(e) => setDueDate(e.target.value)} />}
          </Field>
        </div>
      </div>

      <fieldset className="grid gap-3">
        <legend className="mb-1 text-[13px] font-medium">What it is for <span className="font-normal text-muted-foreground">(before GST)</span></legend>
        {heads.map((head, index) => (
          <div key={head.key} className="grid items-start gap-2 sm:grid-cols-[1fr_11rem_auto]">
            <div>
              <LedgerPicker
                clientId={clientId}
                ledgers={headLedgers}
                value={head.ledger}
                onChange={(id) => setHeads(heads.map((h) => (h.key === head.key ? { ...h, ledger: id } : h)))}
                label={index === 0 ? 'Ledger' : `Ledger ${index + 1}`}
                suggestedGroup={suggestedHeadGroup(kind)}
              />
              {head.description && <p className="mt-1 text-xs text-muted-foreground">{head.description}</p>}
              {errors[`head-${head.key}-ledger`] && <p role="alert" className="mt-1 text-sm text-destructive">{errors[`head-${head.key}-ledger`]}</p>}
            </div>
            <Field label="Amount (₹)" error={errors[`head-${head.key}-amount`]}>
              {(props) => (
                <Input
                  {...props}
                  inputMode="decimal"
                  className="text-right tabular-nums"
                  value={head.amount}
                  onChange={(e) => setHeads(heads.map((h) => (h.key === head.key ? { ...h, amount: e.target.value } : h)))}
                />
              )}
            </Field>
            {heads.length > 1 && (
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove line ${index + 1}`} className="mt-6" onClick={() => setHeads(heads.filter((h) => h.key !== head.key))}>
                <X />
              </Button>
            )}
          </div>
        ))}
        <div>
          <Button type="button" variant="outline" size="sm" onClick={() => setHeads([...heads, blankHead()])}>
            <Plus /> Add another line
          </Button>
        </div>
      </fieldset>

      <fieldset className="grid gap-3">
        <legend className="mb-1 text-[13px] font-medium">GST, as printed on the invoice</legend>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(['cgst', 'sgst', 'igst', 'cess'] as const).map((name) => (
            <Field key={name} label={name === 'cess' ? 'Cess' : name.toUpperCase()}>
              {(props) => (
                <Input
                  {...props}
                  inputMode="decimal"
                  className="text-right tabular-nums"
                  value={tax[name]}
                  onChange={(e) => setTax({ ...tax, [name]: e.target.value })}
                />
              )}
            </Field>
          ))}
        </div>
        <Field label="Round off (₹, + or −)" hint="Positive if the invoice rounds up">
          {(props) => (
            <div className="flex items-center gap-2">
              <Input {...props} inputMode="decimal" className="max-w-[10rem] text-right tabular-nums" value={roundOff} onChange={(e) => setRoundOff(e.target.value)} />
              <Button type="button" variant="outline" size="sm" onClick={roundToRupee} disabled={unreadable || amounts.heads.every((h) => !h.paise)} title="Fill the round off that brings the invoice total to a whole rupee">
                Round off
              </Button>
            </div>
          )}
        </Field>
        {canTds && (
          <details className="rounded-md border border-input px-3 py-2 text-sm" open={!!tds || !!tdsSection || rcm}>
            <summary className="cursor-pointer font-medium">TDS and reverse charge</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="TDS deducted (₹)" hint="Deducted when the bill is booked; the supplier is owed the net.">
                {(props) => <Input {...props} inputMode="decimal" className="text-right tabular-nums" value={tds} onChange={(e) => setTds(e.target.value)} />}
              </Field>
              <Field label="TDS section">
                {(props) => (
                  <Select {...props} value={tdsSection} onChange={(e) => setTdsSection(e.target.value)}>
                    <option value="">None</option>
                    {TDS_SECTIONS.map(([code, label]) => (
                      <option key={code} value={code}>{label}</option>
                    ))}
                  </Select>
                )}
              </Field>
              {canRcm && (
                <div className="sm:col-span-2">
                  <Checkbox label="Reverse charge: the GST is ours to pay, not the supplier’s" checked={rcm} onChange={(e) => setRcm(e.target.checked)} />
                </div>
              )}
            </div>
          </details>
        )}
      </fieldset>

      <details className="rounded-md border border-input px-3 py-2 text-sm">
        <summary className="cursor-pointer font-medium">More details (optional)</summary>
        <div className="mt-3 grid gap-3">
          <Field label="Narration" hint="Worked out from the invoice; change it, or clear it for a standard one.">
            {(props) => <Input {...props} value={narration} onChange={(e) => setNarration(e.target.value)} />}
          </Field>
          {!prefill?.reviseBill && (kind === 'PURCHASE' || kind === 'SALES') && (
            <Field label={kind === 'SALES' ? 'Received into' : 'Paid from'} hint="For a cash bill: it is booked as settled, with its payment. Leave empty to pay later from a bank statement.">
              {(props) => (
                <Select {...props} value={paidFrom} onChange={(e) => setPaidFrom(e.target.value)}>
                  <option value="">Not paid yet</option>
                  {(ledgers.data ?? []).filter((l) => l.group === 'CASH' || l.group === 'BANK').map((l) => (
                    <option key={l.id} value={l.id}>{l.name}</option>
                  ))}
                </Select>
              )}
            </Field>
          )}
        </div>
      </details>
      </div>

      <section aria-label="What this comes to" className="grid gap-1 rounded-md border border-accent-edge bg-accent p-3 text-sm">
        {preview.error && anythingTyped ? (
          <p role="status" className="text-warning">{preview.error}</p>
        ) : (
          <>
            <div className="flex justify-between"><span>Taxable value</span><Money paise={preview.taxable} /></div>
            <div className="flex justify-between"><span>GST</span><Money paise={preview.tax} /></div>
            <div className="flex justify-between border-t border-accent-edge pt-1 font-medium">
              <span>{partyLabel}’s account ({partySide(kind)})</span>
              <Money paise={preview.party} />
            </div>
          </>
        )}
      </section>

      {errors.root && (
        <p role="alert" className="text-sm text-destructive">{errors.root}</p>
      )}

      {layout === 'dialog' && (
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={saving}>{saving ? (prefill?.reviseBill ? 'Saving…' : 'Booking…') : prefill?.reviseBill ? 'Save changes' : 'Book voucher'}</Button>
        </DialogFooter>
      )}
    </form>
  )
}

/** What was read off the receipt beyond the voucher's own fields, so the person sees all of it. */
function PrintedLines({ label, party }: { label: string; party?: PartyFacts }) {
  if (!party || !(party.name || party.gstin || party.address)) return null
  return (
    <div className="grid gap-0.5 text-xs text-muted-foreground" aria-label={label}>
      {party.name && <div>{normaliseName(party.name)}</div>}
      {party.gstin && <div className="num">GSTIN {party.gstin}</div>}
      {party.address && <div>{party.address}</div>}
    </div>
  )
}

function Connector() {
  return (
    <>
      <ArrowRight className="hidden size-5 self-center text-muted-foreground @lg:block" aria-hidden />
      <ArrowDown className="mx-auto size-4 text-muted-foreground @lg:hidden" aria-hidden />
    </>
  )
}

function ReceiptFactsCard({ facts }: { facts: ReceiptFacts }) {
  const rows: [string, string][] = [
    // The seller's address and PAN are in the seller block above.
    ...(facts.seller ? [] : ([['Address', facts.address], ['PAN', facts.pan]] as [string, string][])),
    ['Place of supply', facts.place],
    ['Paid by', PAYMENT_MODE[facts.paymentMode] ?? ''],
    ['Payment terms', facts.terms],
    ['Looks like', facts.category],
    ...DETAIL_LABELS.map(([key, label]): [string, string] => [label, factValue(key, (facts.details ?? {})[key] ?? '')]),
    ['TCS', facts.tcsPaise ? formatPaise(facts.tcsPaise) : ''],
    ['Freight and other charges', facts.otherChargesPaise ? formatPaise(facts.otherChargesPaise) : ''],
    ['Discount', facts.discountPaise ? formatPaise(facts.discountPaise) : ''],
  ]
  const shown = rows.filter(([, v]) => v)
  const foreign = facts.currency && facts.currency !== 'INR'
  const rejected = facts.rejected ?? []
  if (shown.length === 0 && !foreign && rejected.length === 0 && !facts.kindReason && !facts.ownGstinGuess) return null
  return (
    <section aria-label="Read from the receipt" className="grid gap-2 rounded-md border border-accent-edge bg-accent p-3 text-sm">
      <h3 className="text-sm font-semibold text-heading">Read from the receipt</h3>
      {facts.kindReason && <p className="text-info">{facts.kindReason} Check the voucher type below.</p>}
      {facts.ownGstinGuess && (
        <p className="text-muted-foreground">
          The client’s side shows GSTIN <span className="num">{facts.ownGstinGuess}</span>. Add it under GST and every file is told apart exactly.
        </p>
      )}
      {shown.length > 0 && (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            {shown.slice(0, FACTS_SHOWN).map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="min-w-0 break-words">{value}</dd>
              </div>
            ))}
          </dl>
          {shown.length > FACTS_SHOWN && (
            <details className="text-sm">
              <summary className="cursor-pointer font-medium text-link">{shown.length - FACTS_SHOWN} more details from the receipt</summary>
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                {shown.slice(FACTS_SHOWN).map(([label, value]) => (
                  <div key={label} className="contents">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="min-w-0 break-words">{value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </>
      )}
      {foreign && <p className="text-warning">The receipt is in {facts.currency}. Vouchers are booked in rupees: enter the rupee amounts.</p>}
      {rejected.length > 0 && (
        <ul className="grid gap-1 text-warning">
          {rejected.map((r) => (
            <li key={`${r.field}-${r.value}`}>
              {FIELD_NAMES[r.field] ?? r.field.replaceAll('_', ' ')}: the reader saw “{r.value}”, which {r.why}. It was left out; check the receipt.
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function VoucherDialog({
  clientId,
  open,
  onOpenChange,
  initialKind = 'PURCHASE',
  prefill,
}: {
  clientId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  initialKind?: VoucherKind
  prefill?: VoucherPrefill
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="max-h-[92svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{prefill?.reviseBill ? 'Change this bill' : 'Book a voucher'}</DialogTitle>
          <DialogDescription>
            The invoice goes on its own date to the party’s account, so what is owed is always visible. Payments settle it later.
          </DialogDescription>
        </DialogHeader>
        <VoucherForm clientId={clientId} initialKind={initialKind} prefill={prefill} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
