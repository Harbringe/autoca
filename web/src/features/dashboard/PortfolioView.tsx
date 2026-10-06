// The firm's reporting view: how healthy each client's books are, what needs attention (most serious first)
// and what falls due soon. Everything is read from the books on the server; nothing here is scored between people.

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { CalendarClock } from 'lucide-react'
import { useMemo } from 'react'
import { portfolio } from '@/api/queries/dashboard'
import type { AttentionItem, PortfolioClient } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { StatCard, StatGrid } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/table'
import { formatCompact, formatDate, formatPaise, plural } from '@/lib/format'
import { nextTarget, STAGE_LABEL, STAGE_TONE } from '@/lib/overview'

const TONE = { critical: 'danger', high: 'attention', medium: 'neutral' } as const
const SEVERITY_LABEL = { critical: 'Overdue', high: 'Important', medium: 'To do' } as const
const SHOWN = 12

const sum = (rows: PortfolioClient[], pick: (c: PortfolioClient) => number | undefined) =>
  rows.reduce((total, c) => total + (pick(c) ?? 0), 0)

function Money({ paise }: { paise: number | undefined }) {
  if (!paise) return <span className="text-faint">—</span>
  return <span className="num" title={formatPaise(paise)}>{formatCompact(paise)}</span>
}

function booksCell(c: PortfolioClient) {
  if (!c.detail) return <span className="text-faint">—</span>
  const parts: string[] = []
  if (c.approved_through) parts.push(`Approved to ${formatDate(c.approved_through)}`)
  else parts.push('Not approved')
  return (
    <span className="grid gap-0.5 text-xs">
      <span className="text-muted-foreground">{parts[0]}</span>
      {c.changed_since_approval ? <span className="text-accent-foreground">{plural(c.changed_since_approval, 'change')} since</span> : null}
      {c.seal_due ? <span className="text-destructive">Seal due {formatDate(c.seal_due)}</span> : c.next_seal_date ? <span className="text-faint">Next seal {formatDate(c.next_seal_date)}</span> : null}
    </span>
  )
}

export function PortfolioView() {
  const query = useQuery(portfolio())
  const navigate = useNavigate()
  const data = query.data
  const rows = data?.clients ?? []

  const columns: Column<PortfolioClient>[] = useMemo(
    () => [
      { key: 'client', header: 'Client', label: 'Client', sortValue: (c) => c.name.toLowerCase(), sticky: true, cell: (c) => <Link to="/clients/$clientId" params={{ clientId: c.id }} className="block max-w-[26ch] truncate font-medium text-heading hover:underline" title={c.name} onClick={(e) => e.stopPropagation()}>{c.name}</Link> },
      { key: 'stage', header: 'Stage', label: 'Stage', sortValue: (c) => c.stage, cell: (c) => <Badge tone={STAGE_TONE[c.stage] === 'done' ? 'done' : STAGE_TONE[c.stage] === 'attention' ? 'attention' : STAGE_TONE[c.stage] === 'info' ? 'info' : 'neutral'}>{STAGE_LABEL[c.stage]}</Badge> },
      { key: 'books', header: 'Books', cell: booksCell, priority: 2 },
      { key: 'open', header: 'Open items', label: 'Open items', align: 'right', sortValue: (c) => c.open_items ?? 0, priority: 2, cell: (c) => c.detail ? <span className={c.blocking_unexplained ? 'num text-destructive' : 'num'} title={c.blocking_unexplained ? `${c.blocking_unexplained} block sealing` : undefined}>{c.open_items ?? 0}</span> : <span className="text-faint">—</span> },
      { key: 'recv', header: 'Receivable', label: 'Receivable', align: 'right', sortValue: (c) => c.receivables_paise ?? 0, priority: 3, cell: (c) => <Money paise={c.receivables_paise} /> },
      { key: 'pay', header: 'Payable', label: 'Payable', align: 'right', sortValue: (c) => c.payables_paise ?? 0, priority: 3, cell: (c) => <Money paise={c.payables_paise} /> },
      { key: 'tds', header: 'TDS overdue', label: 'TDS overdue', align: 'right', sortValue: (c) => c.tds_overdue_paise ?? 0, priority: 3, cell: (c) => c.tds_overdue_paise ? <span className="num text-destructive" title={formatPaise(c.tds_overdue_paise)}>{formatCompact(c.tds_overdue_paise)}</span> : <span className="text-faint">—</span> },
    ],
    [],
  )

  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  if (query.isLoading || !data) {
    return <div aria-busy="true" aria-live="polite" className="grid gap-4"><span className="sr-only">Loading the portfolio</span><StatGrid aria-hidden>{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-24 rounded-lg" />)}</StatGrid><div className="skeleton h-64 rounded-lg" aria-hidden /></div>
  }
  if (rows.length === 0) return <EmptyState title="No clients yet">Add a client and upload its bank statement to see its books here.</EmptyState>

  const flagged = new Set(data.attention.map((a) => a.client)).size
  const tdsOverdue = sum(rows, (c) => c.tds_overdue_paise)
  const sealDue = rows.filter((c) => c.seal_due).length
  const open = (c: PortfolioClient) => { const target = nextTarget(c.next_step.code); void navigate({ to: target.to, params: { clientId: c.id }, search: target.search as never }) }

  return (
    <div className="grid gap-6 [&>*]:min-w-0">
      <StatGrid>
        <StatCard label="Clients" value={rows.length} note={`${data.by_stage.signed_off} fully signed off`} to="/clients" />
        <StatCard label="Need attention" value={flagged} note={flagged ? `${plural(data.attention.length, 'thing')} to look at` : 'Nothing is flagged'} tone={flagged ? 'attention' : 'plain'} />
        <StatCard label="Seals due" value={sealDue} note={sealDue ? 'Past the date their schedule names' : 'None overdue'} tone={sealDue ? 'attention' : 'plain'} />
        <StatCard label="TDS overdue" value={tdsOverdue ? formatCompact(tdsOverdue) : '—'} valueTitle={tdsOverdue ? formatPaise(tdsOverdue) : undefined} note={tdsOverdue ? 'Deducted, past its due date, not deposited' : 'Nothing past due'} tone={tdsOverdue ? 'attention' : 'plain'} />
      </StatGrid>

      {!data.detailed && <p className="rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground">This firm has many clients, so only the stage and next step are worked out for each here. Open a client for its full picture.</p>}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(18rem,1fr)]">
        <AttentionList items={data.attention} />
        <Deadlines deadlines={data.deadlines} />
      </div>

      <section aria-labelledby="health" className="grid gap-3">
        <div><h2 id="health" className="text-[15px] font-semibold text-heading">Client health</h2><p className="mt-1 text-xs text-muted-foreground">Select a client to continue its next piece of work. Click a column to sort.</p></div>
        <DataTable caption="Client health" columns={columns} rows={rows} rowKey={(c) => c.id} onRowClick={open} defaultSort={{ key: 'client', dir: 'asc' }} />
      </section>
    </div>
  )
}

function AttentionList({ items }: { items: AttentionItem[] }) {
  const shown = items.slice(0, SHOWN)
  return (
    <section aria-labelledby="needs-you" className="grid gap-3 rounded-xl border bg-card p-5">
      <div><h2 id="needs-you" className="text-[15px] font-semibold text-heading">What needs attention</h2><p className="mt-1 text-xs text-muted-foreground">Most serious first. Each line names the client and what is wrong.</p></div>
      {items.length === 0 ? <p className="text-sm text-muted-foreground">Nothing is overdue, unreconciled or waiting past its date.</p> : (
        <ul className="divide-y text-sm">
          {shown.map((item, i) => (
            <li key={`${item.client}-${item.kind}-${i}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5">
              <Badge tone={TONE[item.severity]} className="shrink-0">{SEVERITY_LABEL[item.severity]}</Badge>
              <span className="min-w-0 flex-1 basis-56"><Link to="/clients/$clientId" params={{ clientId: item.client }} className="font-medium text-heading hover:underline">{item.client_name}</Link><span className="block text-[13px] text-muted-foreground">{item.text}</span></span>
            </li>
          ))}
        </ul>
      )}
      {items.length > SHOWN && <p className="text-xs text-muted-foreground">And {items.length - SHOWN} more. Open a client to see all of its items.</p>}
    </section>
  )
}

function Deadlines({ deadlines }: { deadlines: { date: string; label: string; clients: string[] }[] }) {
  return (
    <section aria-labelledby="coming-up" className="grid gap-3 rounded-xl border bg-card p-5">
      <div className="flex items-start justify-between gap-2"><div><h2 id="coming-up" className="text-[15px] font-semibold text-heading">Coming up</h2><p className="mt-1 text-xs text-muted-foreground">TDS deposits and sealing dates in the next 45 days.</p></div><span className="grid size-9 place-items-center rounded-lg bg-accent text-accent-foreground"><CalendarClock className="size-4" /></span></div>
      {deadlines.length === 0 ? <p className="text-sm text-muted-foreground">Nothing falls due in the next 45 days.</p> : (
        <ul className="divide-y text-sm">
          {deadlines.map((d) => (
            <li key={`${d.date}-${d.label}`} className="grid gap-0.5 py-2.5">
              <span className="flex items-baseline justify-between gap-3"><strong className="text-heading">{d.label}</strong><span className="num text-xs text-muted-foreground">{formatDate(d.date)}</span></span>
              <span className="text-[13px] text-muted-foreground">{d.clients.length > 3 ? `${d.clients.slice(0, 3).join(', ')} and ${d.clients.length - 3} more` : d.clients.join(', ')}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
