// Capturing one invoice: the file on one side, the voucher on the other.
//
// A person drops a file; the left side shows a skeleton while it is read, then the document itself as pages (whatever it
// was: PDF, photo, sheet or Word file). The right side is the voucher form, filled in from what was read: who it is from,
// the number, the date, the amounts and the tax. The person completes the rest (what it was for, TDS, notes), checks the
// figures against the page, and books. Purchase or sale is told from the client's own GSTIN, and asked only when it can't be.

import { useQuery } from '@tanstack/react-query'
import { TriangleAlert, UploadCloud, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { ledgers as ledgersQuery } from '@/api/queries/books'
import { useUploadInvoice } from '@/api/queries/bills'
import type { InvoiceReading } from '@/api/types'
import { Button } from '@/components/ui/button'
import { VoucherForm, type VoucherPrefill } from '@/features/bills/VoucherDialog'
import { DocumentViewer, ViewerSkeleton } from '@/features/documents/DocumentViewer'
import { ACCEPT, ACCEPTED_NAME } from '@/lib/fileTypes'
import { cn } from '@/lib/utils'

/** The form's starting values, from what was read. Nothing is booked until a person presses Book. */
export function prefillFrom(reading: InvoiceReading, headLedger?: string): VoucherPrefill | null {
  const read = reading.read
  if (!read) return null
  const purchase = reading.kind !== 'SALES'
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
    headLedger,
  }
}

function FormSkeleton({ animated }: { animated: boolean }) {
  const bar = cn('rounded bg-muted', animated && 'skeleton')
  return (
    <div className="grid gap-4" aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="grid gap-2">
          <div className={cn(bar, 'h-3 w-24')} />
          <div className={cn(bar, 'h-10 w-full')} />
        </div>
      ))}
      <div className={cn(bar, 'h-20 w-full')} />
    </div>
  )
}

export function InvoiceCapture({
  clientId,
  reading,
  onReading,
  onBooked,
}: {
  clientId: string
  /** The invoice on screen, or null. */
  reading: InvoiceReading | null
  onReading: (reading: InvoiceReading | null) => void
  /** Called once it is booked, so the list refreshes. */
  onBooked: () => void
}) {
  const upload = useUploadInvoice(clientId)
  const ledgers = useQuery(ledgersQuery(clientId))
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [readingName, setReadingName] = useState<string | null>(null)

  async function take(file: File | undefined) {
    if (!file) return
    if (!ACCEPTED_NAME.test(file.name)) {
      toast.error('That kind of file cannot be read. Send a PDF, Excel, CSV, Word file or a photo.')
      return
    }
    setReadingName(file.name)
    try {
      const made = await upload.mutateAsync({ file, book: false })
      if (made.status !== 'OPEN') toast.message(made.status === 'DISCARDED' ? 'This file was set aside earlier.' : 'This invoice is already booked.')
      onReading(made)
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setReadingName(null)
      if (input.current) input.current.value = ''
    }
  }

  const busy = upload.isPending
  const kind = reading?.kind ?? ''
  const standard = kind === 'SALES' ? 'Sales' : 'Purchases'
  const headLedger = (ledgers.data ?? []).find((l) => l.name === standard && l.status === 'ACTIVE')?.id
  const prefill = reading && reading.status === 'OPEN' ? prefillFrom(reading, headLedger) : null

  return (
    <section aria-label="Capture an invoice" className="grid gap-4 lg:grid-cols-2 lg:items-stretch">
      <div className="min-w-0 rounded-lg border bg-card p-3">
        <div className="flex h-full min-h-[28rem] flex-col lg:h-[calc(100svh-15rem)] lg:min-h-[32rem]">
          {busy ? (
            <ViewerSkeleton label={`Reading ${readingName ?? 'the file'}…`} />
          ) : reading ? (
            <>
              <div className="mb-2 flex items-center justify-between gap-2 text-sm">
                <span className="min-w-0 truncate font-medium" title={reading.filename}>{reading.filename || 'Invoice'}</span>
                <Button size="sm" variant="ghost" onClick={() => onReading(null)}>
                  <X /> Close
                </Button>
              </div>
              <DocumentViewer documentId={reading.document} className="min-h-0 flex-1" />
            </>
          ) : (
            <button
              type="button"
              onClick={() => input.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(true)
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setOver(false)
                void take(e.dataTransfer.files[0])
              }}
              className={cn(
                'grid h-full flex-1 place-items-center justify-items-center gap-2 rounded-md border-2 border-dashed p-8 text-center transition-colors hover:bg-hover',
                over && 'border-primary bg-hover',
              )}
            >
              <span className="grid justify-items-center gap-2">
                <UploadCloud className="size-9 text-muted-foreground" aria-hidden />
                <span className="font-medium">Drop an invoice here, or click to choose</span>
                <span className="text-xs text-muted-foreground">PDF, Excel, CSV, Word, or a photo. It is read and shown here, and the details fill in on the right.</span>
              </span>
            </button>
          )}
          <input ref={input} type="file" accept={ACCEPT} className="sr-only" aria-label="Choose an invoice file" onChange={(e) => void take(e.target.files?.[0])} />
        </div>
      </div>

      <div className="min-w-0 rounded-lg border bg-card p-4">
        <h2 className="mb-3 text-sm font-semibold text-heading">Invoice details</h2>
        {busy ? (
          <FormSkeleton animated />
        ) : !reading ? (
          <div className="relative">
            <div className="opacity-40">
              <FormSkeleton animated={false} />
            </div>
            <p className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-muted-foreground">
              Upload an invoice and its details fill in here. You complete anything it could not read, and book it.
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {(reading.unreadable_reason || (reading.attention && !(reading.read && !reading.proved))) && reading.status === 'OPEN' && (
              <p className="flex items-start gap-2 rounded-md border border-accent-edge bg-accent p-2 text-sm">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>{reading.unreadable_reason || reading.attention}</span>
              </p>
            )}
            {reading.read && !reading.proved && (
              <p className="rounded-md border border-destructive/40 bg-destructive-bg p-2 text-sm">
                {reading.checks.filter((c) => !c.ok).map((c) => c.detail).join(' ')} Check the figures against the page.
              </p>
            )}
            {reading.status !== 'OPEN' ? (
              <p className="text-sm text-muted-foreground">This invoice is already {reading.status === 'DISCARDED' ? 'set aside' : 'booked'}. Close it to upload another.</p>
            ) : (
              <VoucherForm
                key={reading.id}
                clientId={clientId}
                prefill={prefill ?? { kind: 'PURCHASE', reference: '', cgstPaise: 0, sgstPaise: 0, igstPaise: 0, cessPaise: 0, roundOffPaise: 0, document: reading.document, headLedger }}
                onClose={() => {
                  onBooked()
                  onReading(null)
                }}
              />
            )}
          </div>
        )}
      </div>
    </section>
  )
}
