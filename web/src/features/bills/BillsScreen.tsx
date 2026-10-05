// Purchases & Sales: every invoice and note booked for the client, who it is with, and what is still owing.
//
// Each row is a bill: one invoice booked to its party's own account on its own date, apart from whatever pays it. So this is
// where "what do we owe" and "what are we owed" are answered, and where a bill with no invoice file behind it is visible
// instead of silent. A bill is a permanent fact: it can be removed while the books are a draft and nothing has settled it,
// never edited.

import { useQuery } from '@tanstack/react-query'
import { FileWarning, Lock, Plus, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { bill as billQuery, bills as billsQuery, useRemoveBill } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import type { Bill } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { DataTable, type Column } from '@/components/ui/table'
import { useFy } from '@/features/shell/useFy'
import { formatDate, formatPaise, fyLabel, plural } from '@/lib/format'
import { KIND_LABEL, openPositions, VOUCHER_KINDS } from '@/lib/vouchers'
import { useSession } from '@/session/session'
import { VoucherDialog } from './VoucherDialog'

export function BillsScreen({ clientId, openId }: { clientId: string; openId?: string }) {
  const { fy } = useFy()
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const all = useQuery(billsQuery(clientId))
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [text, setText] = useState('')
  const [booking, setBooking] = useState(false)
  const [open, setOpen] = useState<Bill | null>(null)

  // Arriving with ?bill= (from a voucher in the Day Book) opens that bill, once the list is here.
  useEffect(() => {
    const found = openId ? all.data?.find((b) => b.id === openId) : undefined
    if (found) setOpen(found)
  }, [openId, all.data])

  const mayPost = can('journal.approve') && !!client.data?.can_post
  const inYear = useMemo(() => (all.data ?? []).filter((b) => b.financial_year === fy), [all.data, fy])
  const shown = useMemo(() => {
    const q = text.trim().toLowerCase()
    return inYear
      .filter((b) => !kind || b.kind === kind)
      .filter((b) => !status || (status === 'open' ? b.open_paise > 0 : b.open_paise <= 0))
      .filter((b) => !q || b.reference.toLowerCase().includes(q) || b.party_name.toLowerCase().includes(q))
  }, [inYear, kind, status, text])
  const position = useMemo(() => openPositions(inYear), [inYear])
  const noFile = inYear.filter((b) => !b.has_document).length

  const columns: Column<Bill>[] = [
    { key: 'date', header: 'Date', label: 'Date', cell: (b) => formatDate(b.bill_date), sortValue: (b) => b.bill_date, width: '7rem' },
    { key: 'type', header: 'Type', label: 'Type', cell: (b) => VOUCHER_KINDS.find((k) => k.value === b.kind)?.short ?? b.kind_display, priority: 2, width: '8rem' },
    { key: 'party', header: 'Party', label: 'Party', cell: (b) => <span className="font-medium">{b.party_name}</span>, sortValue: (b) => b.party_name },
    { key: 'ref', header: 'Invoice no.', label: 'Invoice no.', cell: (b) => b.reference, priority: 2, sortValue: (b) => b.reference },
    { key: 'voucher', header: 'Voucher', label: 'Voucher', cell: (b) => (b.entry_no ? `${b.voucher_type} ${b.entry_no}` : '—'), priority: 3 },
    { key: 'total', header: 'Total (₹)', label: 'Total', align: 'right', cell: (b) => <Money display={b.total_display} symbol={false} />, sortValue: (b) => b.total_paise },
    { key: 'open', header: 'Open (₹)', label: 'Open', align: 'right', cell: (b) => <Money display={b.open_display} symbol={false} muted={b.open_paise <= 0} />, sortValue: (b) => b.open_paise },
    {
      key: 'flags',
      header: 'Status',
      label: 'Status',
      cell: (b) => (
        <span className="flex flex-wrap gap-1">
          {b.open_paise <= 0 && <Badge tone="done">Settled</Badge>}
          {!b.has_document && <Badge tone="attention"><FileWarning /> No file</Badge>}
          {b.is_locked && <Badge tone="neutral"><Lock /> Signed off</Badge>}
        </span>
      ),
    },
  ]

  if (all.isError) return <ErrorState error={all.error} retry={() => void all.refetch()} />

  return (
    <div className="grid gap-4">
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input aria-label="Search bills" placeholder="Party or invoice number" className="w-60 pl-8" value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <Select aria-label="Type" className="w-44" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All types</option>
            {VOUCHER_KINDS.map((k) => (
              <option key={k.value} value={k.value}>{k.short}</option>
            ))}
          </Select>
          <Select aria-label="Status" className="w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Open and settled</option>
            <option value="open">Open</option>
            <option value="settled">Settled</option>
          </Select>
        </div>
        {mayPost && (
          <Button onClick={() => setBooking(true)}>
            <Plus /> Book a voucher
          </Button>
        )}
      </div>

      <section aria-label="What is owing" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tile label="Owed to suppliers" paise={position.payables} hint="Purchases still unpaid, less returns" />
        <Tile label="Owed by customers" paise={position.receivables} hint="Sales still unpaid, less returns" />
        <div className="rounded-lg border bg-card p-3">
          <div className="text-xs text-muted-foreground">Bills with no invoice file</div>
          <div className="mt-1 text-lg font-semibold tabular-nums">{noFile}</div>
          <div className="text-xs text-muted-foreground">{noFile ? 'Attach the file so the books can be traced to it.' : 'Every bill has its file.'}</div>
        </div>
      </section>

      <DataTable
        caption={`Purchases and sales, FY ${fyLabel(fy)}`}
        columns={columns}
        rows={shown}
        loading={all.isPending}
        rowKey={(b) => b.id}
        onRowClick={(b) => setOpen(b)}
        defaultSort={{ key: 'date', dir: 'desc' }}
        empty={
          inYear.length === 0 ? (
            <EmptyState
              title={`No purchase or sales vouchers in FY ${fyLabel(fy)}`}
              action={mayPost ? <Button onClick={() => setBooking(true)}><Plus /> Book the first one</Button> : undefined}
            >
              Book a supplier’s invoice or a sales invoice to see what is owed, and settle it from the bank statement later.
            </EmptyState>
          ) : (
            <EmptyState title="No bill matches">
              <button type="button" className="underline" onClick={() => { setText(''); setKind(''); setStatus('') }}>Clear the filters</button>
            </EmptyState>
          )
        }
        footer={
          shown.length ? (
            <tr>
              <td className="px-3 py-2" colSpan={5}>Total ({plural(shown.length, 'bill')})</td>
              <td className="num px-3 py-2 text-right">{formatPaise(shown.reduce((s, b) => s + b.total_paise, 0), { symbol: false })}</td>
              <td className="num px-3 py-2 text-right">{formatPaise(shown.reduce((s, b) => s + b.open_paise, 0), { symbol: false })}</td>
              <td />
            </tr>
          ) : undefined
        }
      />

      {booking && <VoucherDialog clientId={clientId} open onOpenChange={setBooking} />}
      {open && <BillDialog clientId={clientId} summary={open} mayPost={mayPost} onClose={() => setOpen(null)} />}
    </div>
  )
}

function Tile({ label, paise, hint }: { label: string; paise: number; hint: string }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold"><Money paise={paise} /></div>
      <div className="text-xs text-muted-foreground">{hint}</div>
    </div>
  )
}

function BillDialog({ clientId, summary, mayPost, onClose }: { clientId: string; summary: Bill; mayPost: boolean; onClose: () => void }) {
  const detail = useQuery(billQuery(clientId, summary.id))
  const remove = useRemoveBill(clientId)
  const [removing, setRemoving] = useState(false)
  const bill = detail.data

  const settled = (bill?.allocations.length ?? 0) > 0
  const mayRemove = mayPost && !summary.is_locked && !settled

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="sm:left-auto sm:right-0 sm:top-0 sm:h-svh sm:max-h-none sm:w-full sm:max-w-xl sm:translate-x-0 sm:translate-y-0 sm:content-start sm:rounded-none sm:border-y-0 sm:border-r-0"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>{KIND_LABEL[summary.kind] ?? summary.kind_display} · {summary.reference}</DialogTitle>
          <DialogDescription>
            {summary.party_name} · {formatDate(summary.bill_date)}
            {summary.due_date ? ` · due ${formatDate(summary.due_date)}` : ''}
            {summary.voucher_type ? ` · ${summary.voucher_type} No. ${summary.entry_no}` : ''}
          </DialogDescription>
        </DialogHeader>

        {detail.isPending ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : detail.isError ? (
          <ErrorState error={detail.error} retry={() => void detail.refetch()} />
        ) : (
          bill && (
            <div className="grid gap-4">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">Taxable value</dt><dd className="text-right"><Money display={bill.taxable_display} /></dd>
                <dt className="text-muted-foreground">GST</dt>
                <dd className="text-right"><Money paise={bill.cgst_paise + bill.sgst_paise + bill.igst_paise + bill.cess_paise} /></dd>
                {bill.round_off_paise !== 0 && (<><dt className="text-muted-foreground">Round off</dt><dd className="text-right"><Money display={bill.round_off_display} /></dd></>)}
                {bill.tds_paise > 0 && (<><dt className="text-muted-foreground">TDS deducted</dt><dd className="text-right"><Money display={bill.tds_display} /></dd></>)}
                <dt className="font-medium">On the party’s account</dt><dd className="text-right font-medium"><Money display={bill.total_display} /></dd>
                <dt className="font-medium">Still open</dt><dd className="text-right font-medium"><Money display={bill.open_display} /></dd>
              </dl>
              {bill.rcm && <p className="text-sm text-muted-foreground">Reverse charge: the GST is the client’s own liability, not part of what the party is owed.</p>}

              <DataTable
                caption={`Lines of ${bill.voucher_type} No. ${bill.entry_no}`}
                rows={bill.lines}
                rowKey={(l) => String(l.id)}
                columns={[
                  { key: 'ledger', header: 'Particulars', label: 'Particulars', cell: (l) => <span>{l.ledger_name}{l.party_name ? <span className="text-muted-foreground"> · {l.party_name}</span> : null}</span> },
                  { key: 'dr', header: 'Debit (₹)', label: 'Debit', align: 'right', cell: (l) => (l.direction === 'DR' ? <Money display={l.amount_display} symbol={false} /> : <span aria-hidden>—</span>) },
                  { key: 'cr', header: 'Credit (₹)', label: 'Credit', align: 'right', cell: (l) => (l.direction === 'CR' ? <Money display={l.amount_display} symbol={false} /> : <span aria-hidden>—</span>) },
                ]}
              />
              {bill.narration && <p className="text-sm text-muted-foreground">{bill.narration}</p>}

              <div>
                <h3 className="mb-1 text-[13px] font-medium">Settled by</h3>
                {bill.allocations.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nothing yet. A payment from the bank statement will settle it.</p>
                ) : (
                  <ul className="grid gap-1 text-sm">
                    {bill.allocations.map((a) => (
                      <li key={a.id} className="flex justify-between gap-3">
                        <span>{a.kind_display} · {a.voucher_type} No. {a.entry_no}, {formatDate(a.entry_date)}</span>
                        <Money display={a.amount_display} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {!bill.has_document && (
                <p role="status" className="flex items-center gap-2 text-sm text-warning"><FileWarning className="size-4" aria-hidden /> No invoice file is attached to this bill.</p>
              )}
              {summary.is_locked && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Lock className="size-4" aria-hidden /> In signed-off books; it can no longer be removed.</p>}
              {settled && !summary.is_locked && <p className="text-sm text-muted-foreground">It has payments against it, so it cannot be removed. Record a debit or credit note to adjust it.</p>}

              {mayRemove && (
                <div className="flex justify-end">
                  <Button variant="outline" onClick={() => setRemoving(true)}>Remove this bill</Button>
                </div>
              )}
            </div>
          )
        )}

        <Confirm
          open={removing}
          onOpenChange={setRemoving}
          title={`Remove ${summary.reference}?`}
          confirmLabel="Remove bill"
          destructive
          note="optional"
          noteLabel="Why (kept in the change log)"
          onConfirm={async (note) => {
            try {
              await remove.mutateAsync({ id: summary.id, note })
              toast.success(`${summary.reference} removed`)
              onClose()
            } catch (e) {
              toast.error(messageOf(e))
              throw e
            }
          }}
        >
          <p>
            The voucher and its entries leave the books, and {summary.party_name}’s account goes back to what it was. What it was is kept in the change log.
          </p>
        </Confirm>
      </DialogContent>
    </Dialog>
  )
}
