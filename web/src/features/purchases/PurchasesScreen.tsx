// Purchases & Sales, as a claim report is laid out in an expense tool: one list, a row for every receipt however it arrived.
//
// A file dropped here is read (its supplier, number, date, amounts, tax, address, lines) and, when everything proves, booked at
// once as an ordinary bill; anything unsure waits as a row with an alert saying why. Click a row and it opens on a page of
// its own: the form on the left, the document on the right. Bills keyed in by hand are rows in the same list.

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { CirclePlus, FileText, FilePenLine, ListChecks, MoreHorizontal, Search, TriangleAlert, Upload } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { bills as billsQuery, invoiceReadings, useDeleteInvoice, useRemoveBill, useUploadInvoice } from '@/api/queries/bills'
import { clientDetail, V1 } from '@/api/queries/clients'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useFy } from '@/features/shell/useFy'
import { ACCEPT, ACCEPTED_NAME } from '@/lib/fileTypes'
import { financialYearOf, formatDate, formatPaise, fyLabel, plural } from '@/lib/format'
import { isPurchaseSide, KIND_LABEL, openPositions, type VoucherKind } from '@/lib/vouchers'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { buildItems, type ListItem } from './model'

type Side = 'ALL' | 'PURCHASE' | 'SALES'

const sideOf = (kind: string): Side => (kind ? (isPurchaseSide(kind as VoucherKind) ? 'PURCHASE' : 'SALES') : 'ALL')

export function PurchasesScreen({ clientId }: { clientId: string }) {
  const { fy } = useFy()
  const { can } = useSession()
  const navigate = useNavigate()
  const client = useQuery(clientDetail(clientId))
  const readings = useQuery(invoiceReadings(clientId))
  const bills = useQuery(billsQuery(clientId))
  const upload = useUploadInvoice(clientId)
  const deleteInvoice = useDeleteInvoice(clientId)
  const removeBill = useRemoveBill(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [side, setSide] = useState<Side>('ALL')
  const [text, setText] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [processing, setProcessing] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  const [alerts, setAlerts] = useState(false)
  const [deleting, setDeleting] = useState<ListItem[] | null>(null)
  const [showAside, setShowAside] = useState(false)

  const mayUpload = can('document.upload') && !!client.data?.can_post
  const mayPost = can('journal.approve') && !!client.data?.can_post

  const all = useMemo(() => buildItems(readings.data ?? [], bills.data ?? []), [readings.data, bills.data])
  // A row belongs to the year its invoice is dated in; a file not yet read has no date and is shown whatever the year.
  const inYear = useMemo(() => all.filter((i) => !i.date || financialYearOf(i.date) === fy), [all, fy])
  const aside = inYear.filter((i) => i.setAside)
  const live = inYear.filter((i) => !i.setAside)
  const shown = useMemo(() => {
    const q = text.trim().toLowerCase()
    return (showAside ? inYear : live)
      .filter((i) => side === 'ALL' || sideOf(i.kind) === side)
      .filter((i) => !q || i.party.toLowerCase().includes(q) || i.reference.toLowerCase().includes(q) || i.filename.toLowerCase().includes(q))
  }, [inYear, live, side, text, showAside])
  const counts = { ALL: live.length, PURCHASE: live.filter((i) => sideOf(i.kind) === 'PURCHASE').length, SALES: live.filter((i) => sideOf(i.kind) === 'SALES').length }
  const position = useMemo(() => openPositions((bills.data ?? []).filter((b) => b.financial_year === fy)), [bills.data, fy])
  const alertItems = live.filter((i) => i.alerts.length > 0)
  const waiting = live.filter((i) => i.status === 'Needs you')

  const open = (item: ListItem) => void navigate({ to: '/clients/$clientId/bills/$itemId', params: { clientId, itemId: item.id }, search: { as: item.as } })

  async function pick(files: FileList | File[] | null) {
    const chosen = [...(files ?? [])]
    if (!chosen.length) return
    let booked = 0
    let needing = 0
    let last: string | null = null
    for (const file of chosen) {
      if (!ACCEPTED_NAME.test(file.name)) {
        toast.error(`${file.name}: that kind of file cannot be read. Send a PDF, Excel, CSV, Word file or a photo.`)
        continue
      }
      setProcessing((p) => [...p, file.name])
      try {
        const made = await upload.mutateAsync({ file })
        if (made.status === 'BOOKED') booked += 1
        else needing += 1
        last = made.id
      } catch (e) {
        toast.error(`${file.name}: ${messageOf(e)}`)
      } finally {
        setProcessing((p) => p.filter((n) => n !== file.name))
      }
    }
    if (input.current) input.current.value = ''
    if (booked) toast.success(`${plural(booked, 'receipt')} read and booked${needing ? `; ${needing} need${needing === 1 ? 's' : ''} you` : ''}`)
    else if (needing) toast.message(`${plural(needing, 'receipt')} read; ${needing === 1 ? 'it needs' : 'they need'} you`)
    // One file that needs a person opens at once: that is the form to fill in.
    if (chosen.length === 1 && needing === 1 && last) void navigate({ to: '/clients/$clientId/bills/$itemId', params: { clientId, itemId: last }, search: { as: 'reading' } })
  }

  async function confirmDelete() {
    for (const item of deleting ?? []) {
      if (item.readingId) await deleteInvoice.mutateAsync({ id: item.readingId, withBill: !!item.billId, releasePayments: true })
      else if (item.billId) await removeBill.mutateAsync({ id: item.billId, note: 'Removed from the list', releasePayments: true })
    }
    toast.success('Deleted')
    setSelected(new Set())
  }

  if (readings.isError) return <ErrorState error={readings.error} retry={() => void readings.refetch()} />
  if (bills.isError) return <ErrorState error={bills.error} retry={() => void bills.refetch()} />
  if (readings.isPending || bills.isPending) return <Spinner label="Loading purchases and sales…" />

  const empty = live.length === 0 && processing.length === 0
  const pickedItems = shown.filter((i) => selected.has(i.id))
  const toggle = (id: string) => setSelected((s) => (s.has(id) ? new Set([...s].filter((x) => x !== id)) : new Set(s).add(id)))
  const allSelected = shown.length > 0 && pickedItems.length === shown.length

  const fileInput = (
    <input ref={input} type="file" multiple accept={ACCEPT} className="sr-only" aria-label="Choose receipts" onChange={(e) => void pick(e.target.files)} />
  )

  return (
    <div
      className={cn('grid gap-4 rounded-lg', dragging && 'outline-2 outline-dashed outline-primary')}
      onDragOver={(e) => {
        if (!mayUpload) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
      onDrop={(e) => {
        if (!mayUpload) return
        e.preventDefault()
        setDragging(false)
        void pick(e.dataTransfer.files)
      }}
    >
      {fileInput}
      <div className="no-print flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-heading">Purchases &amp; Sales</h2>
          <p className="text-sm text-muted-foreground">
            FY {fyLabel(fy)} · owed to suppliers <Money paise={position.payables} /> · owed by customers <Money paise={position.receivables} />
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => setAlerts(true)} disabled={alertItems.length === 0}>
            <TriangleAlert className="text-warning" /> View alerts{alertItems.length ? ` (${alertItems.length})` : ''}
          </Button>
        </div>
      </div>

      {empty ? (
        <section aria-label="No purchases or sales yet" className="grid justify-items-center gap-6 py-10 text-center">
          <div>
            <h3 className="text-xl font-semibold text-heading">No purchases or sales in FY {fyLabel(fy)}</h3>
            <p className="mt-1 text-sm text-muted-foreground">Upload receipts and the form fills itself in from what is printed on them.</p>
          </div>
          <div className="grid w-full max-w-3xl gap-3 sm:grid-cols-3">
            <EntryCard
              icon={<Upload className="size-5 text-primary" />}
              title="Upload receipts"
              hint="Drag and drop or select from device"
              disabled={!mayUpload}
              onClick={() => input.current?.click()}
            />
            <EntryCard
              icon={<FilePenLine className="size-5 text-primary" />}
              title="Create manually"
              hint="Enter the details yourself"
              disabled={!mayPost}
              onClick={() => void navigate({ to: '/clients/$clientId/bills/$itemId', params: { clientId, itemId: 'new' }, search: { as: 'new', kind: 'PURCHASE' } })}
            />
            <EntryCard
              icon={<ListChecks className="size-5 text-primary" />}
              title={`Waiting for you (${waiting.length})`}
              hint="Receipts read but not booked"
              disabled={waiting.length === 0}
              onClick={() => waiting[0] && open(waiting[0])}
            />
          </div>
        </section>
      ) : (
        <>
          <div className="no-print flex flex-wrap items-center justify-between gap-3">
            <div role="tablist" aria-label="Which vouchers" className="flex gap-1 rounded-md border bg-card p-0.5">
              {(
                [
                  ['ALL', 'All'],
                  ['PURCHASE', 'Purchases'],
                  ['SALES', 'Sales'],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={side === id}
                  onClick={() => setSide(id)}
                  className={cn('rounded px-3 py-1 text-sm font-medium', side === id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-hover')}
                >
                  {label} <span className="opacity-70">{counts[id]}</span>
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <Input aria-label="Search" placeholder="Party, invoice number or file" className="w-60 pl-8" value={text} onChange={(e) => setText(e.target.value)} />
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button disabled={!mayUpload && !mayPost}>
                    <CirclePlus /> Add
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem disabled={!mayUpload} onSelect={() => input.current?.click()}>
                    <Upload /> Upload receipts
                  </DropdownMenuItem>
                  <DropdownMenuItem disabled={!mayPost} onSelect={() => void navigate({ to: '/clients/$clientId/bills/$itemId', params: { clientId, itemId: 'new' }, search: { as: 'new', kind: 'PURCHASE' } })}>
                    <FilePenLine /> Create a purchase
                  </DropdownMenuItem>
                  <DropdownMenuItem disabled={!mayPost} onSelect={() => void navigate({ to: '/clients/$clientId/bills/$itemId', params: { clientId, itemId: 'new' }, search: { as: 'new', kind: 'SALES' } })}>
                    <FilePenLine /> Create a sale
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button variant="outline" disabled={pickedItems.length !== 1} onClick={() => pickedItems[0] && open(pickedItems[0])}>
                Edit
              </Button>
              <Button variant="outline" disabled={!mayPost || pickedItems.length === 0} onClick={() => setDeleting(pickedItems)}>
                Delete
              </Button>
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg border bg-card">
            <table className="w-full min-w-[56rem] text-sm">
              <caption className="sr-only">Purchases and sales, FY {fyLabel(fy)}</caption>
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="w-10 px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      className="size-4"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(shown.map((i) => i.id)))}
                    />
                  </th>
                  <th scope="col" className="w-12 px-2 py-2 font-medium">Alerts</th>
                  <th scope="col" className="px-2 py-2 font-medium">Date</th>
                  <th scope="col" className="px-2 py-2 font-medium">Receipt</th>
                  <th scope="col" className="px-2 py-2 font-medium">Type</th>
                  <th scope="col" className="px-2 py-2 font-medium">Party details</th>
                  <th scope="col" className="px-2 py-2 font-medium">Invoice no.</th>
                  <th scope="col" className="px-2 py-2 font-medium">Status</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">Amount</th>
                  <th scope="col" className="w-12 px-2 py-2 text-center font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {processing.map((name) => (
                  <tr key={`p-${name}`} className="border-b" aria-busy="true">
                    <td colSpan={10} className="px-3 py-3 text-center text-muted-foreground">
                      <span className="mr-2 inline-flex gap-0.5" aria-hidden>
                        <i className="size-1.5 animate-pulse rounded-full bg-primary" />
                        <i className="size-1.5 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
                        <i className="size-1.5 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
                      </span>
                      Processing {name}
                    </td>
                  </tr>
                ))}
                {shown.map((item) => (
                  <tr key={item.id} className={cn('cursor-pointer border-b hover:bg-hover', selected.has(item.id) && 'bg-hover')} onClick={() => open(item)}>
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" className="size-4" aria-label={`Select ${item.party}`} checked={selected.has(item.id)} onChange={() => toggle(item.id)} />
                    </td>
                    <td className="px-2 text-center">
                      {item.alerts.length > 0 && (
                        <span title={item.alerts.join(' ')} role="img" aria-label={`Alert: ${item.alerts.join(' ')}`}>
                          <TriangleAlert className="size-4 text-warning" />
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2 tabular-nums">{item.date ? formatDate(item.date) : '—'}</td>
                    <td className="px-2">
                      {item.documentId ? (
                        <img
                          src={`${V1}/documents/${item.documentId}/preview/1/`}
                          alt=""
                          loading="lazy"
                          className="h-10 w-8 rounded-sm border bg-white object-cover object-top"
                        />
                      ) : (
                        <FileText className="size-5 text-muted-foreground" aria-label="No file" />
                      )}
                    </td>
                    <td className="px-2">{item.kind ? (KIND_LABEL[item.kind] ?? item.kind) : <span className="text-muted-foreground">Not known</span>}</td>
                    <td className="px-2 py-2">
                      <div className="font-medium">{item.party}</div>
                      {item.detail && <div className="max-w-xs truncate text-xs text-muted-foreground">{item.detail}</div>}
                    </td>
                    <td className="px-2">{item.reference || '—'}</td>
                    <td className="px-2">
                      <Badge tone={item.tone}>{item.status}</Badge>
                    </td>
                    <td className="num px-2 text-right">{item.paise != null ? formatPaise(item.paise) : '—'}</td>
                    <td className="px-2 text-center" onClick={(e) => e.stopPropagation()}>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button size="icon" variant="ghost" aria-label={`Actions for ${item.party}`}>
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onSelect={() => open(item)}>Open</DropdownMenuItem>
                          <DropdownMenuItem disabled={!mayPost} onSelect={() => setDeleting([item])}>
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && processing.length === 0 && (
                  <tr>
                    <td colSpan={10} className="px-3 py-8 text-center text-muted-foreground">
                      Nothing matches.{' '}
                      <button type="button" className="underline" onClick={() => { setText(''); setSide('ALL') }}>Clear the filters</button>
                    </td>
                  </tr>
                )}
              </tbody>
              {shown.length > 0 && (
                <tfoot>
                  <tr className="font-semibold">
                    <td colSpan={8} className="px-3 py-2">Total ({plural(shown.length, 'row')})</td>
                    <td className="num px-2 py-2 text-right">{formatPaise(shown.reduce((sum, i) => sum + (i.paise ?? 0), 0))}</td>
                    <td />
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          {aside.length > 0 && (
            <button type="button" className="no-print w-fit text-sm text-muted-foreground underline" onClick={() => setShowAside((v) => !v)}>
              {showAside ? 'Hide' : 'Show'} {plural(aside.length, 'receipt')} set aside
            </button>
          )}
        </>
      )}

      <Dialog open={alerts} onOpenChange={setAlerts}>
        <DialogContent aria-describedby={undefined} className="max-h-[80svh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Alerts</DialogTitle>
            <DialogDescription>Rows that need a look, and why.</DialogDescription>
          </DialogHeader>
          <ul className="grid gap-3">
            {alertItems.map((i) => (
              <li key={i.id} className="rounded-md border p-3 text-sm">
                <button type="button" className="font-medium underline" onClick={() => { setAlerts(false); open(i) }}>
                  {i.party}
                  {i.reference ? ` · ${i.reference}` : ''}
                </button>
                <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                  {i.alerts.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>

      <Confirm
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={deleting && deleting.length > 1 ? `Delete ${deleting.length} rows?` : 'Delete this row?'}
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
      >
        <p>
          Each uploaded file and what was read from it is deleted. Where a bill was booked from it, the bill and its voucher are taken out of the books too (what it
          was is kept in the change log). Payments settled against a bill are un-linked and stay on the party’s account. This is refused once the books are signed off.
        </p>
      </Confirm>
    </div>
  )
}

function EntryCard({ icon, title, hint, disabled, onClick }: { icon: React.ReactNode; title: string; hint: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="grid justify-items-center gap-1 rounded-lg border bg-card p-5 text-center shadow-sm transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
    >
      {icon}
      <span className="mt-1 font-semibold text-heading">{title}</span>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </button>
  )
}
