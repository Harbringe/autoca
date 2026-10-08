// Booking a purchase or sales voucher: who it is with, what it is for, the tax as printed, and what the party's account
// will be left at.
//
// The figures at the bottom are a preview worked out as you type (src/lib/vouchers.ts). The server re-does the
// arithmetic and is the authority: what it refuses, it says in words, and those words are shown as they are. So the
// preview can only ever be early, never different.

import { useQuery } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import { ledgers as ledgersQuery, parties as partiesQuery } from '@/api/queries/books'
import { usePostBill, useReviseBill } from '@/api/queries/bills'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BillCreateRequest, InvoiceReading, Party } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { Button } from '@/components/ui/button'
import { Checkbox, Select } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { LedgerPicker, usableLedgers } from '@/features/review/LedgerPicker'
import { formatDate, parseDate, parseRupees } from '@/lib/format'
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
export interface ReceiptFacts {
  address: string
  pan: string
  place: string
  terms: string
  paymentMode: string
  currency: string
  category: string
  unsure: string[]
}

const PAYMENT_MODE: Record<string, string> = { cash: 'Cash', card: 'Card', upi: 'UPI', bank_transfer: 'Bank transfer', cheque: 'Cheque', credit: 'On credit (not yet paid)' }

const NEW_PARTY = '__new__'

/** What an uploaded invoice was read as, to start the form from. The person still confirms every field. */
export interface VoucherPrefill {
  kind: VoucherKind
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
}: {
  clientId: string
  /** Called after it is booked, and by Cancel. */
  onClose: () => void
  initialKind?: VoucherKind
  prefill?: VoucherPrefill
  /** ``page``: tabs for Details and Itemizations, and no buttons of its own (the page's Save button submits it by ``formId``). */
  layout?: 'dialog' | 'page'
  formId?: string
}) {
  const parties = useQuery(partiesQuery(clientId))
  const ledgers = useQuery(ledgersQuery(clientId))
  const post = usePostBill(clientId)
  const revise = useReviseBill(clientId)
  const invalidate = useInvalidateClient(clientId)

  const [kind, setKind] = useState<VoucherKind>(prefill?.kind ?? initialKind)
  const [partyId, setPartyId] = useState(prefill?.partyId ?? '')
  const [reference, setReference] = useState(prefill?.reference ?? '')
  const [billDate, setBillDate] = useState(() => formatDate(prefill?.billDate ?? new Date().toISOString().slice(0, 10)))
  const [dueDate, setDueDate] = useState(prefill?.dueDate ? formatDate(prefill.dueDate) : '')
  const [tab, setTab] = useState<'details' | 'items'>('details')
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
  const [narration, setNarration] = useState('')
  const [ownGstin, setOwnGstin] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [newParty, setNewParty] = useState<{ name: string; gstin: string } | null>(prefill?.newParty ?? null)
  const [saving, setSaving] = useState(false)

  const purchaseSide = isPurchaseSide(kind)
  const canTds = kind === 'PURCHASE'
  const canRcm = kind === 'PURCHASE'
  const items = prefill?.items ?? []
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
    setPartyId('')
    setRcm(false)
    setTds('')
    setTdsSection('')
    setNewParty(null)
    setErrors({})
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
      document: prefill?.document ?? null,
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
            <p className="text-sm text-muted-foreground">No lines were read from this invoice. The whole taxable value goes to the ledger on the Details tab; add more lines there to split it.</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-sm">
                  <caption className="sr-only">Lines as printed on the invoice</caption>
                  <thead className="border-b text-left text-xs text-muted-foreground">
                    <tr>
                      {['Description', 'HSN/SAC', 'Qty', 'Rate (₹)', 'Amount (₹)', 'GST %'].map((h, i) => (
                        <th key={h} scope="col" className={cn('px-1 py-1 font-medium', i >= 2 && 'text-right')}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((i, n) => (
                      <tr key={n} className="border-b border-dashed">
                        <td className="px-1 py-1.5">{i.description}</td>
                        <td className="px-1">{i.hsn_sac || '—'}</td>
                        <td className="num px-1 text-right">{i.quantity ? `${i.quantity}${i.unit ? ` ${i.unit}` : ''}` : '—'}</td>
                        <td className="num px-1 text-right">{i.rate_paise != null ? (i.rate_paise / 100).toFixed(2) : '—'}</td>
                        <td className="num px-1 text-right">{i.amount_paise != null ? (i.amount_paise / 100).toFixed(2) : '—'}</td>
                        <td className="num px-1 text-right">{i.gst_rate ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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
      <Field label="Voucher type">
        {(props) => (
          <Select {...props} value={kind} onChange={(e) => changeKind(e.target.value as VoucherKind)}>
            {VOUCHER_KINDS.map((k) => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </Select>
        )}
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Field label={partyLabel} error={errors.party}>
            {(props) => (
              <Select
                {...props}
                value={newParty ? NEW_PARTY : partyId}
                onChange={(e) => {
                  if (e.target.value === NEW_PARTY) {
                    setNewParty({ name: '', gstin: '' })
                    setPartyId('')
                  } else {
                    setNewParty(null)
                    setPartyId(e.target.value)
                  }
                }}
              >
                <option value="">Choose…</option>
                {suitable.map((p) => (
                  <option key={p.id} value={p.id}>{p.canonical_name}</option>
                ))}
                <option value={NEW_PARTY}>+ Add a new {partyLabel.toLowerCase()}…</option>
              </Select>
            )}
          </Field>
          {newParty && (
            <fieldset className="grid gap-2 rounded-md border border-input bg-card p-3">
              <Field label="Name" error={errors.newPartyName}>
                {(props) => <Input {...props} autoFocus value={newParty.name} onChange={(e) => setNewParty({ ...newParty, name: e.target.value })} />}
              </Field>
              <Field label="GSTIN (leave blank if unregistered)" error={errors.newPartyGstin} mask="gstin">
                {(props, m) => <Input {...props} {...m} value={newParty.gstin} onChange={(e) => setNewParty({ ...newParty, gstin: e.target.value })} />}
              </Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" size="sm" onClick={() => setNewParty(null)}>Cancel</Button>
                <Button type="button" size="sm" disabled={!newParty.name.trim()} onClick={() => void createParty()}>
                  Add {partyLabel.toLowerCase()}
                </Button>
              </div>
            </fieldset>
          )}
        </div>
        <Field label="Invoice number" error={errors.reference} hint="As printed on the document. The same number from the same party is refused as a duplicate.">
          {(props) => <Input {...props} autoComplete="off" value={reference} onChange={(e) => setReference(e.target.value)} />}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Invoice date" error={errors.bill_date}>
          {(props) => <DateInput {...props} value={billDate} onChange={(e) => setBillDate(e.target.value)} />}
        </Field>
        <Field label="Due date (optional)" error={errors.due_date}>
          {(props) => <DateInput {...props} value={dueDate} onChange={(e) => setDueDate(e.target.value)} />}
        </Field>
      </div>

      <fieldset className="grid gap-3">
        <legend className="mb-1 text-[13px] font-medium">What it is for (taxable value, before GST)</legend>
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
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Round off (₹, + or −)" hint="Positive if the invoice rounds up.">
            {(props) => <Input {...props} inputMode="decimal" className="text-right tabular-nums" value={roundOff} onChange={(e) => setRoundOff(e.target.value)} />}
          </Field>
          {canTds && (
            <>
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
            </>
          )}
        </div>
        {canRcm && (
          <Checkbox label="Reverse charge: the GST is ours to pay, not the supplier’s" checked={rcm} onChange={(e) => setRcm(e.target.checked)} />
        )}
      </fieldset>

      <details className="rounded-md border border-input px-3 py-2 text-sm">
        <summary className="cursor-pointer font-medium">More details (optional)</summary>
        <div className="mt-3 grid gap-3">
          <Field label="Narration" hint="Leave blank for a standard one.">
            {(props) => <Input {...props} value={narration} onChange={(e) => setNarration(e.target.value)} />}
          </Field>
          <Field label="Your GSTIN for this invoice" hint="Only needed if the client has more than one." error={errors.own_gstin} mask="gstin">
            {(props, m) => <Input {...props} {...m} value={ownGstin} onChange={(e) => setOwnGstin(e.target.value)} />}
          </Field>
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
function ReceiptFactsCard({ facts }: { facts: ReceiptFacts }) {
  const rows: [string, string][] = [
    ['Address', facts.address],
    ['PAN', facts.pan],
    ['Place of supply', facts.place],
    ['Paid by', PAYMENT_MODE[facts.paymentMode] ?? ''],
    ['Payment terms', facts.terms],
    ['Looks like', facts.category],
  ]
  const shown = rows.filter(([, v]) => v)
  const foreign = facts.currency && facts.currency !== 'INR'
  if (shown.length === 0 && !foreign) return null
  return (
    <section aria-label="Read from the receipt" className="grid gap-2 rounded-md border border-accent-edge bg-accent p-3 text-sm">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Read from the receipt</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        {shown.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {foreign && <p className="text-warning">The receipt is in {facts.currency}. Vouchers are booked in rupees: enter the rupee amounts.</p>}
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
