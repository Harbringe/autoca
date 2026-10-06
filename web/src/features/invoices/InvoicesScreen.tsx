// Invoices: files the client has sent, and what each appears to say.
//
// An upload is stored with the client's other documents and read into a draft, with the arithmetic that proves it (taxable
// value plus tax equals the total, GSTINs well-formed). Nothing is booked from here on its own: a person books each one,
// which opens the ordinary voucher form already filled in from the file, or attaches it to a bill they keyed in earlier, or
// sets it aside. Until then it is an open item, so a file cannot sit unseen.

import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleX, FileUp } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { invoiceReadings, useDecideInvoice, useUploadInvoice } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import type { InvoiceReading } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Spinner } from '@/components/ui/spinner'
import { VoucherDialog, type VoucherPrefill } from '@/features/bills/VoucherDialog'
import { formatDate, plural } from '@/lib/format'
import { useSession } from '@/session/session'

const STATUS_TONE: Record<string, 'attention' | 'done' | 'neutral'> = { OPEN: 'attention', BOOKED: 'done', ATTACHED: 'done', DISCARDED: 'neutral' }

function prefillOf(reading: InvoiceReading): VoucherPrefill | null {
  const read = reading.read
  if (!read) return null
  const purchase = reading.kind === 'PURCHASE'
  return {
    kind: purchase ? 'PURCHASE' : 'SALES',
    partyId: reading.suggested_party?.id,
    newParty: reading.suggested_party || !purchase ? undefined : { name: read.supplier_name, gstin: read.counterparty_gstin },
    reference: read.invoice_no,
    billDate: read.invoice_date,
    taxablePaise: read.taxable_paise,
    cgstPaise: read.cgst_paise,
    sgstPaise: read.sgst_paise,
    igstPaise: read.igst_paise,
    cessPaise: read.cess_paise,
    roundOffPaise: read.round_off_paise,
    document: reading.document,
  }
}

export function InvoicesScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const list = useQuery(invoiceReadings(clientId))
  const upload = useUploadInvoice(clientId)
  const decide = useDecideInvoice(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [kind, setKind] = useState<'PURCHASE' | 'SALES'>('PURCHASE')
  const [booking, setBooking] = useState<InvoiceReading | null>(null)
  const mayUpload = can('document.upload')
  const mayDecide = can('journal.approve') && !!client.data?.can_post

  async function pick(files: FileList | null) {
    const file = files?.[0]
    if (!file) return
    try {
      const made = await upload.mutateAsync({ file, kind })
      toast.success(made.read ? `${file.name} read: ${made.proved ? 'it adds up' : 'check the figures'}` : `${file.name} stored; it could not be read`)
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      if (input.current) input.current.value = ''
    }
  }

  async function act(reading: InvoiceReading, action: 'attach' | 'discard') {
    try {
      await decide.mutateAsync({ id: reading.id, action, bill: reading.matching_bill?.id })
      toast.success(action === 'attach' ? 'Attached to the bill' : 'Set aside')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  if (list.isPending) return <Spinner label="Loading invoices…" />
  if (list.isError) return <ErrorState error={list.error} retry={() => void list.refetch()} />
  const readings = list.data
  const waiting = readings.filter((r) => r.status === 'OPEN').length

  return (
    <div className="grid gap-4">
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {waiting === 0 ? 'Nothing is waiting.' : `${plural(waiting, 'invoice')} waiting for you.`} Each file is read, never booked on its own.
        </p>
        {mayUpload && (
          <div className="flex items-center gap-2">
            <Select aria-label="Kind of invoice" className="w-44" value={kind} onChange={(e) => setKind(e.target.value as 'PURCHASE' | 'SALES')}>
              <option value="PURCHASE">Purchase invoice</option>
              <option value="SALES">Sales invoice</option>
            </Select>
            <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only" aria-label="Choose an invoice PDF" onChange={(e) => void pick(e.target.files)} />
            <Button onClick={() => input.current?.click()} disabled={upload.isPending}>
              <FileUp /> {upload.isPending ? 'Reading…' : 'Upload an invoice'}
            </Button>
          </div>
        )}
      </div>

      {readings.length === 0 ? (
        <EmptyState title="No invoices uploaded yet">Upload a supplier's or your own sales invoice as a PDF; it is read and checked, and you book it.</EmptyState>
      ) : (
        <ul className="grid gap-2">
          {readings.map((r) => (
            <li key={r.id} className="grid gap-2 rounded-md border bg-card p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{r.filename || 'Invoice'}</div>
                  <div className="text-xs text-muted-foreground">
                    {r.kind === 'PURCHASE' ? 'Purchase' : 'Sales'} · uploaded {formatDate(r.created_at.slice(0, 10))}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {r.read?.total_display && <Money display={r.read.total_display} />}
                  <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{r.status_display}</Badge>
                </div>
              </div>

              {r.unreadable_reason ? (
                <p className="text-sm text-muted-foreground">{r.unreadable_reason}</p>
              ) : (
                r.read && (
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
                  </div>
                )
              )}

              {r.status === 'OPEN' && mayDecide && (
                <div className="flex flex-wrap justify-end gap-2">
                  {r.matching_bill && (
                    <Button variant="outline" size="sm" onClick={() => void act(r, 'attach')}>
                      Attach to {r.matching_bill.party_name}’s bill {r.matching_bill.reference}
                    </Button>
                  )}
                  {r.read && (
                    <Button size="sm" onClick={() => setBooking(r)}>
                      Book it
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => void act(r, 'discard')}>
                    Set aside
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {booking && prefillOf(booking) && (
        <VoucherDialog clientId={clientId} open onOpenChange={(open) => !open && setBooking(null)} prefill={prefillOf(booking) ?? undefined} />
      )}
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
