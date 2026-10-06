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
import { usePostBill } from '@/api/queries/bills'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BillCreateRequest, Party } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { Button } from '@/components/ui/button'
import { Checkbox, Select } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { LedgerPicker, usableLedgers } from '@/features/review/LedgerPicker'
import { formatDate, parseDate, parseRupees } from '@/lib/format'
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
}

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
  document: string
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
  const parties = useQuery(partiesQuery(clientId))
  const ledgers = useQuery(ledgersQuery(clientId))
  const post = usePostBill(clientId)
  const invalidate = useInvalidateClient(clientId)

  const [kind, setKind] = useState<VoucherKind>(prefill?.kind ?? initialKind)
  const [partyId, setPartyId] = useState(prefill?.partyId ?? '')
  const [reference, setReference] = useState(prefill?.reference ?? '')
  const [billDate, setBillDate] = useState(() => formatDate(prefill?.billDate ?? new Date().toISOString().slice(0, 10)))
  const [dueDate, setDueDate] = useState('')
  const [heads, setHeads] = useState<Head[]>(() => [{ ...blankHead(), amount: asRupees(prefill?.taxablePaise) }])
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
      narration: narration.trim(),
      own_gstin: ownGstin.trim().toUpperCase(),
      document: prefill?.document ?? null,
    }
    setSaving(true)
    try {
      const made = await post.mutateAsync(body)
      toast.success(`${made.voucher_type} No. ${made.entry_no} booked · ${made.reference}`)
      reset()
      onOpenChange(false)
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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="max-h-[92svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Book a voucher</DialogTitle>
          <DialogDescription>
            The invoice goes on its own date to the {partyLabel.toLowerCase()}’s account, so what is owed is always visible. Payments settle it later.
          </DialogDescription>
        </DialogHeader>

        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
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

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? 'Booking…' : 'Book voucher'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
