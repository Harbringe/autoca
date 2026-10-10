// One purchase or sale on a page of its own: the form on the left, the receipt on the right.
//
// The form is filled in from the receipt (supplier, number, date, due date, amounts, tax, lines, how it was paid), shows what
// was read beside it, and is saved as an ordinary booked bill. The receipt is the document itself, as pages, which can be
// zoomed, turned, hidden, and opened in full. Opened from a row of the list: an uploaded invoice (``reading``), a bill with
// no file (``bill``), or a new one keyed in (``new``).

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronLeft, EyeOff, MoreHorizontal, PanelRight, Sparkles, TriangleAlert, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { ledgers as ledgersQuery } from '@/api/queries/books'
import {
  bill as billQuery,
  bills as billsQuery,
  invoiceReadings,
  useDecideInvoice,
  useDeleteInvoice,
  useRemoveBill,
  useRereadInvoice,
  useUploadInvoice,
} from '@/api/queries/bills'
import { clientDetail, V1 } from '@/api/queries/clients'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Spinner } from '@/components/ui/spinner'
import { PartyStatementDialog } from '@/features/bills/PartyStatementDialog'
import { VoucherForm, type VoucherPrefill } from '@/features/bills/VoucherDialog'
import { DocumentViewer, ViewerSkeleton } from '@/features/documents/DocumentViewer'
import { usableLedgers } from '@/features/review/LedgerPicker'
import { ACCEPT, ACCEPTED_NAME } from '@/lib/fileTypes'
import { formatDate, formatPaise } from '@/lib/format'
import { normaliseName } from '@/lib/names'
import { KIND_LABEL, NOT_A_HEAD, type VoucherKind } from '@/lib/vouchers'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { suggestLedger } from './model'
import { blankPrefill, prefillFromReading, prefillOfBill } from './prefill'

export function ExpensePage({ clientId, itemId, as, kind }: { clientId: string; itemId: string; as: 'reading' | 'bill' | 'new'; kind?: VoucherKind }) {
  const { can } = useSession()
  const navigate = useNavigate()
  const client = useQuery(clientDetail(clientId))
  const readings = useQuery(invoiceReadings(clientId))
  const bills = useQuery(billsQuery(clientId))
  const ledgers = useQuery(ledgersQuery(clientId))
  const upload = useUploadInvoice(clientId)
  const decide = useDecideInvoice(clientId)
  const deleteInvoice = useDeleteInvoice(clientId)
  const removeBill = useRemoveBill(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [viewer, setViewer] = useState(true)
  const [alerts, setAlerts] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const reread = useRereadInvoice(clientId)
  const [formTab, setFormTab] = useState<'details' | 'items'>('details')
  const [statement, setStatement] = useState(false)
  const [uploadingName, setUploadingName] = useState<string | null>(null)
  const [over, setOver] = useState(false)

  const reading = as === 'reading' ? readings.data?.find((r) => r.id === itemId) : as === 'bill' ? readings.data?.find((r) => r.bill === itemId) : undefined
  const billId = as === 'bill' ? itemId : (reading?.bill ?? null)
  const detail = useQuery({ ...billQuery(clientId, billId ?? ''), enabled: !!billId })
  const mayPost = can('journal.approve') && !!client.data?.can_post
  const mayUpload = can('document.upload') && !!client.data?.can_post

  const listPath = () => void navigate({ to: '/clients/$clientId/bills', params: { clientId } })

  async function take(file: File | undefined) {
    if (!file) return
    if (!ACCEPTED_NAME.test(file.name)) {
      toast.error('That kind of file cannot be read. Send a PDF, Excel, CSV, Word file or a photo.')
      return
    }
    setUploadingName(file.name)
    try {
      const made = await upload.mutateAsync({ file, book: false })
      if (made.status !== 'OPEN') toast.message(made.status === 'DISCARDED' ? 'This file was set aside earlier.' : 'This invoice is already booked.')
      void navigate({ to: '/clients/$clientId/bills/$itemId', params: { clientId, itemId: made.id }, search: { as: 'reading' }, replace: true })
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setUploadingName(null)
      if (input.current) input.current.value = ''
    }
  }

  if (as !== 'new' && (readings.isPending || bills.isPending)) return <Spinner label="Loading…" />
  if (readings.isError) return <ErrorState error={readings.error} retry={() => void readings.refetch()} />
  const known = as === 'new' || reading || (as === 'bill' && bills.data?.some((b) => b.id === itemId))
  if (!known) {
    return (
      <div className="grid gap-3 py-10 text-center">
        <p className="font-medium">This purchase or sale is not here any more.</p>
        <div><Button variant="outline" onClick={listPath}>Back to Purchases &amp; Sales</Button></div>
      </div>
    )
  }
  if (billId && detail.isPending) return <Spinner label="Loading the bill…" />
  if (detail.isError) return <ErrorState error={detail.error} retry={() => void detail.refetch()} />

  const bill = detail.data
  const read = reading?.read ?? null
  const openForm = !bill && (as === 'new' || (reading?.status === 'OPEN'))
  const suggestedKind = read?.suggested_kind === 'SALES' || read?.suggested_kind === 'PURCHASE' ? read.suggested_kind : undefined
  const readingKind = reading?.kind === 'SALES' || reading?.kind === 'PURCHASE' ? reading.kind : suggestedKind
  const wantedKind: VoucherKind = (bill?.kind as VoucherKind | undefined) ?? readingKind ?? kind ?? 'PURCHASE'
  const heads = usableLedgers(ledgers.data).filter((l) => !NOT_A_HEAD.has(l.group ?? ''))
  const standard = heads.find((l) => l.name === (wantedKind === 'SALES' ? 'Sales' : 'Purchases') && l.status === 'ACTIVE')?.id
  const headLedger = (read?.expense_hint && suggestLedger(read.expense_hint, heads)) || standard

  const prefill: VoucherPrefill | null = bill
    ? prefillOfBill(bill, bill.document ?? reading?.document, reading)
    : reading
      ? (prefillFromReading(reading, headLedger) ?? blankPrefill(wantedKind, standard))
      : blankPrefill(wantedKind, standard)
  const documentId = bill?.document ?? reading?.document ?? null
  const filename = reading?.filename ?? ''

  const total = bill ? bill.total_paise : (read?.total_paise ?? null)
  const counterparty = readingKind === 'SALES' ? read?.buyer_name : readingKind === 'PURCHASE' ? read?.supplier_name : ''
  const party = normaliseName(bill?.party_name ?? counterparty ?? '')
  const title = `${KIND_LABEL[wantedKind] ?? 'Voucher'}${party ? ` · ${party}` : ''}${total != null ? `  ${formatPaise(total)}` : ''}`
  const alertList = [
    reading?.unreadable_reason || reading?.attention || '',
    ...(read && reading && !reading.proved ? reading.checks.filter((c) => !c.ok).map((c) => c.detail) : []),
    ...((read?.unsure ?? []).length ? [`The reader was not sure of: ${read!.unsure.join(', ')}. Check against the page.`] : []),
    ...(bill && !bill.has_document ? ['No invoice file is attached to this bill.'] : []),
    ...(reading?.payments ?? []).map((p) =>
      p.evidence === 'amount'
        ? `A bank row of exactly this amount may be its payment (the payee is not confirmed, so check): ${formatDate(p.date)} · ${p.narration || 'a bank row'}.`
        : `Looks already paid: ${formatDate(p.date)} · ${p.narration || 'a bank row'}.`,
    ),
  ].filter(Boolean)
  const status = bill ? (bill.open_paise <= 0 ? 'Settled' : 'Booked') : as === 'new' ? 'Not booked' : reading?.status === 'DISCARDED' ? 'Set aside' : 'Needs you'
  const settled = (bill?.allocations.length ?? 0) > 0

  async function act(action: 'attach' | 'discard') {
    if (!reading) return
    try {
      await decide.mutateAsync({ id: reading.id, action, bill: reading.matching_bill?.id })
      toast.success(action === 'attach' ? 'Attached to the bill' : 'Set aside')
      listPath()
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function readAgain() {
    if (!reading) return
    try {
      await reread.mutateAsync({ id: reading.id })
      toast.success('Read again')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function remove() {
    if (reading) await deleteInvoice.mutateAsync({ id: reading.id, withBill: !!reading.bill, releasePayments: true })
    else if (billId) await removeBill.mutateAsync({ id: billId, note: 'Removed from its page', releasePayments: true })
    toast.success('Deleted')
    listPath()
  }

  const formId = 'expense-form'
  const busy = !!uploadingName

  return (
    <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" style={viewer ? undefined : { gridTemplateColumns: 'minmax(0,1fr)' }}>
      <input ref={input} type="file" accept={ACCEPT} className="sr-only" aria-label="Choose a receipt" onChange={(e) => void take(e.target.files?.[0])} />

      <section aria-label="Form" className={cn('min-w-0 pb-10 lg:pr-6', !viewer && 'mx-auto w-full max-w-3xl')}>
        <Link to="/clients/$clientId/bills" params={{ clientId }} className="no-print inline-flex items-center gap-1 text-sm text-primary hover:underline">
          <ChevronLeft className="size-4" aria-hidden /> Purchases &amp; Sales
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-xl font-semibold text-heading">{as === 'new' && !reading ? `New ${KIND_LABEL[wantedKind]?.toLowerCase() ?? 'voucher'}` : title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={bill ? 'done' : status === 'Needs you' ? 'attention' : 'neutral'}>{status}</Badge>
              {read && !bill && (
                <span className="inline-flex items-center gap-1 text-primary">
                  <Sparkles className="size-4" aria-hidden /> AI-assisted
                </span>
              )}
              {bill?.entry_no ? <span className="text-muted-foreground">{bill.voucher_type} No. {bill.entry_no}</span> : null}
            </div>
          </div>
          <div className="no-print flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => setAlerts(true)} disabled={alertList.length === 0}>
              <TriangleAlert className="text-warning" /> View alerts{alertList.length ? ` (${alertList.length})` : ''}
            </Button>
            {(openForm || bill) && mayPost && (
              <Button type="submit" form={formId}>
                {bill ? 'Save changes' : wantedKind === 'SALES' ? 'Save sale' : wantedKind === 'PURCHASE' ? 'Save purchase' : 'Save'}
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon" variant="outline" aria-label="More">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {reading?.matching_bill && (
                  <DropdownMenuItem onSelect={() => void act('attach')}>
                    Attach to {reading.matching_bill.party_name}’s bill {reading.matching_bill.reference}
                  </DropdownMenuItem>
                )}
                {bill && <DropdownMenuItem onSelect={() => setStatement(true)}>Statement of account</DropdownMenuItem>}
                {reading?.status === 'OPEN' && mayPost && !bill && (
                  <DropdownMenuItem disabled={reread.isPending} onSelect={() => void readAgain()}>Read the file again</DropdownMenuItem>
                )}
                {reading?.status === 'OPEN' && mayPost && <DropdownMenuItem onSelect={() => void act('discard')}>Set aside</DropdownMenuItem>}
                {(reading || bill) && (
                  <DropdownMenuItem disabled={!mayPost || (!!bill && bill.is_locked)} onSelect={() => setDeleting(true)}>
                    Delete
                  </DropdownMenuItem>
                )}
                {!viewer && (
                  <DropdownMenuItem onSelect={() => setViewer(true)}>Show receipt viewer</DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        <div className="mt-5">
          {busy ? (
            <FormSkeleton />
          ) : !mayPost && !bill && (reading?.status !== 'OPEN' || as === 'new') ? (
            <p className="text-sm text-muted-foreground">You can look at this but not book it.</p>
          ) : reading && reading.status !== 'OPEN' && !bill ? (
            <p className="text-sm text-muted-foreground">This file is {reading.status === 'DISCARDED' ? 'set aside' : 'already booked'}.</p>
          ) : (
            <>
              {reading && read && !reading.proved && (
                <p className="mb-3 rounded-md border border-destructive/40 bg-destructive-bg p-2 text-sm">
                  {reading.checks.filter((c) => !c.ok).map((c) => c.detail).join(' ')} Check the figures against the page.
                </p>
              )}
              <VoucherForm
                // Reading the file again changes what the form starts from, so it starts afresh from the new reading.
                key={`${itemId}-${bill?.id ?? ''}-${headLedger ?? ''}-${read ? 'r' : ''}-${read?.items?.length ?? 0}-${read?.invoice_no ?? ''}-${reading?.kind ?? ''}-${read?.suggested_kind ?? ''}`}
                clientId={clientId}
                layout="page"
                formId={formId}
                tab={formTab}
                onTabChange={setFormTab}
                onReadAgain={reading?.status === 'OPEN' && mayPost && !bill ? () => void readAgain() : undefined}
                readingAgain={reread.isPending}
                prefill={prefill ?? undefined}
                initialKind={wantedKind}
                onClose={listPath}
              />
            </>
          )}

          {bill && (
            <section aria-label="On the books" className="mt-6 grid gap-3 rounded-lg border bg-card p-4 text-sm">
              <h3 className="font-semibold text-heading">On the books</h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">On the party’s account</dt><dd className="text-right"><Money display={bill.total_display} /></dd>
                <dt className="text-muted-foreground">Still open</dt><dd className="text-right"><Money display={bill.open_display} /></dd>
              </dl>
              <div>
                <h4 className="mb-1 text-[13px] font-medium">Settled by</h4>
                {bill.allocations.length === 0 ? (
                  <p className="text-muted-foreground">Nothing yet. A payment from the bank statement will settle it.</p>
                ) : (
                  <ul className="grid gap-1">
                    {bill.allocations.map((a) => (
                      <li key={a.id} className="flex justify-between gap-3">
                        <span>{a.kind_display} · {a.voucher_type} No. {a.entry_no}, {formatDate(a.entry_date)}</span>
                        <Money display={a.amount_display} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {bill.is_locked && <p className="text-muted-foreground">In signed-off books: it can no longer be removed.</p>}
              {settled && !bill.is_locked && <p className="text-muted-foreground">It has payments against it. Deleting it un-links them (they stay on the party’s account); saving changes keeps them.</p>}
            </section>
          )}
        </div>
      </section>

      {viewer && (
        <aside aria-label="Receipt" className="min-w-0 border-t pt-4 lg:sticky lg:top-4 lg:h-[calc(100svh-7rem)] lg:self-start lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
          <div className="flex h-full min-h-[28rem] flex-col">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-heading">Receipt</h3>
              <Button size="sm" variant="outline" onClick={() => setViewer(false)}>
                <EyeOff /> Hide receipt viewer
              </Button>
            </div>
            {busy ? (
              <ViewerSkeleton label={`Reading ${uploadingName}…`} />
            ) : documentId ? (
              <>
                <DocumentViewer documentId={documentId} className="min-h-0 flex-1" />
                <div className="mt-2 flex items-center justify-between gap-2 border-t pt-2 text-sm">
                  <span className="min-w-0 truncate text-muted-foreground" title={filename}>{filename || 'Invoice file'}</span>
                  <div className="flex gap-1">
                    {mayUpload && !bill && as !== 'reading' && (
                      <Button size="sm" variant="ghost" onClick={() => input.current?.click()}>Add</Button>
                    )}
                    <Button asChild size="sm" variant="ghost">
                      <a href={`${V1}/documents/${documentId}/download/`} target="_blank" rel="noreferrer">Open</a>
                    </Button>
                  </div>
                </div>
              </>
            ) : (
              <button
                type="button"
                disabled={!mayUpload}
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
                  'grid flex-1 place-items-center rounded-md border-2 border-dashed p-8 text-center transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60',
                  over && 'border-primary bg-hover',
                )}
              >
                <span className="grid justify-items-center gap-2">
                  <Upload className="size-9 text-muted-foreground" aria-hidden />
                  <span className="font-medium">Upload or drag and drop the receipt here</span>
                  <span className="text-xs text-muted-foreground">PDF, Excel, CSV, Word or a photo. The form fills in from it.</span>
                  <span className="mt-2 inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm text-primary">
                    <Upload className="size-4" /> Upload new receipt
                  </span>
                </span>
              </button>
            )}
          </div>
        </aside>
      )}
      {!viewer && (
        <Button size="icon" variant="outline" className="no-print fixed bottom-6 right-6 shadow-md" aria-label="Show receipt viewer" onClick={() => setViewer(true)}>
          <PanelRight />
        </Button>
      )}

      <Dialog open={alerts} onOpenChange={setAlerts}>
        <DialogContent aria-describedby={undefined} className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Alerts</DialogTitle>
            <DialogDescription>What to look at before saving.</DialogDescription>
          </DialogHeader>
          <ul className="grid list-disc gap-2 pl-5 text-sm">
            {alertList.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>

      {statement && bill && <PartyStatementDialog clientId={clientId} partyId={bill.party} partyName={bill.party_name} onClose={() => setStatement(false)} />}

      <Confirm
        open={deleting}
        onOpenChange={setDeleting}
        title={bill ? 'Delete this purchase or sale?' : 'Delete this receipt?'}
        confirmLabel="Delete"
        destructive
        onConfirm={remove}
      >
        <p>
          {bill
            ? `The bill and its voucher are taken out of the books (what it was is kept in the change log), and the uploaded file is deleted.${settled ? ' Payments settled against it are un-linked and stay on the party’s account.' : ''} This is refused once the books are signed off.`
            : 'The uploaded file and what was read from it are deleted for good.'}
        </p>
      </Confirm>
    </div>
  )
}

function FormSkeleton() {
  return (
    <div className="grid gap-4" aria-hidden aria-busy="true">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="grid gap-2">
          <div className="skeleton h-3 w-24 rounded" />
          <div className="skeleton h-10 w-full rounded" />
        </div>
      ))}
    </div>
  )
}
