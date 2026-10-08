// Invoices: capture one with the file beside its form, and see what became of every file sent.
//
// Capture (InvoiceCapture): drop a file, see it as pages on the left, and complete the voucher on the right, which is filled
// in from what was read. Below, every file sent: the ones the system booked itself, and those waiting for a person.
//
// An upload is stored with the client's other documents, read (its text, or for a scan the vision model), and told apart as
// a purchase or a sale by the client's own GSTIN. When everything is certain it is booked at once as an ordinary bill, which
// can be changed here. When anything is not certain nothing is booked: the file waits with the reason in words, and it is an
// open item and an alert, so staff deal with exactly that: say which it is, check the figures, or book it by hand.

import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleX, FileUp, Trash2, TriangleAlert } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { invoiceReadings, useDecideInvoice, useDeleteInvoice, useSayInvoiceKind, useUploadInvoice } from '@/api/queries/bills'
import { clientDetail, V1 } from '@/api/queries/clients'
import type { BillDetail, InvoiceReading } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { Confirm } from '@/components/ca/Confirm'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { VoucherDialog, type VoucherPrefill } from '@/features/bills/VoucherDialog'
import { InvoiceCapture } from './InvoiceCapture'
import { ACCEPT } from '@/lib/fileTypes'
import { formatDate, plural } from '@/lib/format'
import { useSession } from '@/session/session'

function statusOf(r: InvoiceReading): { label: string; tone: 'attention' | 'done' | 'neutral' } {
  if (r.status === 'BOOKED') return { label: r.auto_booked ? 'Booked automatically' : 'Booked', tone: 'done' }
  if (r.status === 'ATTACHED') return { label: 'Attached to a bill', tone: 'done' }
  if (r.status === 'DISCARDED') return { label: 'Set aside', tone: 'neutral' }
  return { label: 'Needs you', tone: 'attention' }
}

const KIND_LABEL: Record<string, string> = { PURCHASE: 'Purchase', SALES: 'Sales', '': 'Purchase or sale not known' }

/** The booked bill as a form to change: its figures, and the ledger its taxable value went to. */
function prefillOfBill(bill: BillDetail, document: string): VoucherPrefill {
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
  }
}

export function InvoicesScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const list = useQuery(invoiceReadings(clientId))
  const upload = useUploadInvoice(clientId)
  const decide = useDecideInvoice(clientId)
  const sayKind = useSayInvoiceKind(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [changing, setChanging] = useState<VoucherPrefill | null>(null)
  const [capture, setCapture] = useState<InvoiceReading | null>(null)
  const [deleting, setDeleting] = useState<InvoiceReading | null>(null)
  const deleteInvoice = useDeleteInvoice(clientId)
  const mayUpload = can('document.upload')
  const mayDecide = can('journal.approve') && !!client.data?.can_post

  async function pick(files: FileList | null) {
    const chosen = [...(files ?? [])]
    let booked = 0
    let waiting = 0
    for (const file of chosen) {
      try {
        const made = await upload.mutateAsync({ file })
        if (made.status === 'BOOKED') booked += 1
        else waiting += 1
      } catch (e) {
        toast.error(`${file.name}: ${messageOf(e)}`)
      }
    }
    if (input.current) input.current.value = ''
    if (booked) toast.success(`${plural(booked, 'invoice')} read and booked${waiting ? `; ${waiting} need${waiting === 1 ? 's' : ''} you` : ''}`)
    else if (waiting) toast.message(`${plural(waiting, 'invoice')} read; ${waiting === 1 ? 'it needs' : 'they need'} you`)
  }

  async function act(reading: InvoiceReading, action: 'attach' | 'discard') {
    try {
      await decide.mutateAsync({ id: reading.id, action, bill: reading.matching_bill?.id })
      toast.success(action === 'attach' ? 'Attached to the bill' : 'Set aside')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function say(reading: InvoiceReading, kind: 'PURCHASE' | 'SALES') {
    try {
      const made = await sayKind.mutateAsync({ id: reading.id, kind })
      if (made.status === 'BOOKED') toast.success('Booked')
      else toast.message(made.attention || 'Noted. It still needs you.')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function change(reading: InvoiceReading) {
    try {
      const bill = await raw.get<BillDetail>(`${V1}/clients/${clientId}/bills/${reading.bill}/`)
      setChanging(prefillOfBill(bill, reading.document))
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  if (list.isPending) return <Spinner label="Loading invoices…" />
  if (list.isError) return <ErrorState error={list.error} retry={() => void list.refetch()} />
  const readings = list.data
  const waiting = readings.filter((r) => r.status === 'OPEN').length

  return (
    <div className="grid gap-4 [&>*]:min-w-0">
      {mayUpload && mayDecide && (
        <InvoiceCapture clientId={clientId} reading={capture} onReading={setCapture} onBooked={() => void list.refetch()} />
      )}

      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-heading">Every file sent</h2>
          <p className="text-sm text-muted-foreground">
            {waiting === 0 ? 'Nothing is waiting.' : `${plural(waiting, 'invoice')} waiting for you.`} Certain invoices are booked automatically; anything
            unsure waits here.
          </p>
        </div>
        {mayUpload && (
          <>
            <input
              ref={input}
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              aria-label="Choose invoice files"
              onChange={(e) => void pick(e.target.files)}
            />
            <Button variant="outline" onClick={() => input.current?.click()} disabled={upload.isPending}>
              <FileUp /> {upload.isPending ? 'Reading…' : 'Upload many, book automatically'}
            </Button>
          </>
        )}
      </div>

      {readings.length === 0 ? (
        <EmptyState title="No invoices uploaded yet">Upload purchase and sales invoices as PDF, Excel, Word or photos; each is read, checked and booked when certain.</EmptyState>
      ) : (
        <ul className="grid gap-2">
          {readings.map((r) => {
            const status = statusOf(r)
            return (
              <li key={r.id} className="grid gap-2 rounded-md border bg-card p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{r.filename || 'Invoice'}</div>
                    <div className="text-xs text-muted-foreground">
                      {KIND_LABEL[r.kind] ?? r.kind} · uploaded {formatDate(r.created_at.slice(0, 10))}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {r.read?.total_display && <Money display={r.read.total_display} />}
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </div>
                </div>

                {r.status === 'OPEN' && (r.attention || r.unreadable_reason) && (
                  <p className="flex items-start gap-2 rounded-md border border-accent-edge bg-accent p-2 text-sm">
                    <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                    <span>{r.attention || r.unreadable_reason}</span>
                  </p>
                )}

                {!r.unreadable_reason && r.read && (
                  <div className="grid gap-1 text-sm">
                    <div>
                      {r.read.supplier_name || 'Unnamed'} · invoice {r.read.invoice_no || '—'} · {r.read.invoice_date ? formatDate(r.read.invoice_date) : 'no date'}
                    </div>
                    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                      {r.checks.map((c) => (
                        <li key={c.name} className={c.ok ? 'flex items-center gap-1 text-success' : 'flex items-center gap-1 text-destructive'}>
                          {c.ok ? <CircleCheck className="size-3.5" aria-hidden /> : <CircleX className="size-3.5" aria-hidden />}
                          {c.ok ? CHECK_LABEL[c.name] ?? c.name : c.detail}
                        </li>
                      ))}
                    </ul>
                    {r.suggested_party && <div className="text-xs text-muted-foreground">Looks like {r.suggested_party.name}.</div>}
                    {r.payments?.map((p) => (
                      <div key={`${p.date}-${p.narration}`} className="rounded-md border border-accent-edge bg-accent p-2 text-xs">
                        <strong>{r.auto_booked && p.on_party_account ? 'Matched to its payment:' : 'Looks already paid:'}</strong> {formatDate(p.date)} · {p.narration || 'a bank row'}.{' '}
                        {p.on_party_account
                          ? 'It is on the party’s account.'
                          : p.posted_to
                            ? `It was posted to ${p.posted_to}, so the invoice counts that cost or income twice. Move that payment onto the party’s account from To fix.`
                            : 'It is still waiting in Review. Place it on the party’s account.'}
                      </div>
                    ))}
                  </div>
                )}

                {r.status === 'OPEN' && mayDecide && (
                  <div className="flex flex-wrap justify-end gap-2">
                    {!r.kind && r.read && (
                      <>
                        <Button variant="outline" size="sm" onClick={() => void say(r, 'PURCHASE')} disabled={sayKind.isPending}>
                          It’s a purchase
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => void say(r, 'SALES')} disabled={sayKind.isPending}>
                          It’s a sale
                        </Button>
                      </>
                    )}
                    {r.matching_bill && (
                      <Button variant="outline" size="sm" onClick={() => void act(r, 'attach')}>
                        Attach to {r.matching_bill.party_name}’s bill {r.matching_bill.reference}
                      </Button>
                    )}
                    {r.read && (
                      <Button
                        size="sm"
                        onClick={() => {
                          setCapture(r)
                          window.scrollTo({ top: 0, behavior: 'smooth' })
                        }}
                      >
                        Fill in and book
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" onClick={() => void act(r, 'discard')}>
                      Set aside
                    </Button>
                  </div>
                )}

                {mayDecide && (r.status === 'DISCARDED' || r.status === 'OPEN' || r.bill) && (
                  <div className="flex justify-end">
                    <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setDeleting(r)} aria-label={`Delete ${r.filename || 'this invoice'}`}>
                      <Trash2 /> {r.bill ? 'Delete with its bill' : 'Delete'}
                    </Button>
                  </div>
                )}

                {r.status === 'BOOKED' && r.bill && mayDecide && (
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {r.auto_booked && <span className="text-xs text-muted-foreground">Check it; change it if anything is wrong.</span>}
                    <Button variant="outline" size="sm" onClick={() => void change(r)}>
                      Change
                    </Button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <Confirm
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={deleting?.bill ? 'Delete this invoice and its bill?' : 'Delete this invoice?'}
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (!deleting) return
          await deleteInvoice.mutateAsync({ id: deleting.id, withBill: !!deleting.bill })
          if (capture?.id === deleting.id) setCapture(null)
          toast.success('Deleted')
        }}
      >
        <p>
          {deleting?.bill
            ? 'The bill and its voucher are taken out of the books (what it was is kept in the change log), and the uploaded file is deleted. This is refused if a payment is settled against the bill or the books are signed off.'
            : 'The uploaded file and what was read from it are deleted for good.'}
        </p>
      </Confirm>

      {changing && <VoucherDialog clientId={clientId} open onOpenChange={(open) => !open && setChanging(null)} prefill={changing} />}
    </div>
  )
}

const CHECK_LABEL: Record<string, string> = {
  amounts_found: 'Amounts found',
  arithmetic: 'Taxable value and tax add up to the total',
  tax_split: 'Tax split is consistent',
  gstin: 'GSTIN is well-formed',
  invoice_no: 'Invoice number found',
  invoice_date: 'Date looks right',
}
