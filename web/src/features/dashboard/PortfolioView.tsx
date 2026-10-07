// The detail table under the dashboards: every client the signed-in person can see, one line each, with
// where its books stand, what is open and what is late. Everything is read from the books on the server;
// nothing here is scored between people.

import { useNavigate, Link } from '@tanstack/react-router'
import { useMemo } from 'react'
import type { PortfolioClient, Portfolio } from '@/api/types'
import { DashCard, type CardState } from '@/components/ca/DashCard'
import { Badge } from '@/components/ui/badge'
import { DataTable, type Column } from '@/components/ui/table'
import { clientHealth } from '@/lib/dashboard'
import { formatCompact, formatDate, formatPaise, plural } from '@/lib/format'
import { nextTarget, STAGE_LABEL, STAGE_TONE } from '@/lib/overview'

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

export function ClientHealthTable({ data, state }: { data: Portfolio | undefined; state: CardState }) {
  const navigate = useNavigate()
  const rows = data?.clients ?? []
  const columns: Column<PortfolioClient>[] = useMemo(
    () => [
      { key: 'client', header: 'Client', label: 'Client', sortValue: (c) => c.name.toLowerCase(), sticky: true, cell: (c) => <Link to="/clients/$clientId" params={{ clientId: c.id }} className="block max-w-[26ch] truncate font-medium text-heading hover:underline" title={c.name} onClick={(e) => e.stopPropagation()}>{c.name}</Link> },
      { key: 'stage', header: 'Stage', label: 'Stage', sortValue: (c) => c.stage, cell: (c) => <Badge tone={STAGE_TONE[c.stage] === 'done' ? 'done' : STAGE_TONE[c.stage] === 'attention' ? 'attention' : STAGE_TONE[c.stage] === 'info' ? 'info' : 'neutral'}>{STAGE_LABEL[c.stage]}</Badge> },
      { key: 'health', header: 'Standing', label: 'Standing', sortValue: (c) => ['overdue', 'at_risk', 'on_track'].indexOf(clientHealth(c).health), cell: (c) => { const h = clientHealth(c); return <Badge tone={h.health === 'overdue' ? 'danger' : h.health === 'at_risk' ? 'attention' : 'done'} title={h.reasons.join(', ') || undefined}>{h.health === 'overdue' ? 'Late' : h.health === 'at_risk' ? 'At risk' : 'On track'}</Badge> } },
      { key: 'books', header: 'Books', cell: booksCell, priority: 2 },
      { key: 'open', header: 'Open items', label: 'Open items', align: 'right', sortValue: (c) => c.open_items ?? 0, priority: 2, cell: (c) => c.detail ? <span className={c.blocking_unexplained ? 'num text-destructive' : 'num'} title={c.blocking_unexplained ? `${c.blocking_unexplained} block sealing` : undefined}>{c.open_items ?? 0}</span> : <span className="text-faint">—</span> },
      { key: 'recv', header: 'Receivable', label: 'Receivable', align: 'right', sortValue: (c) => c.receivables_paise ?? 0, priority: 3, cell: (c) => <Money paise={c.receivables_paise} /> },
      { key: 'pay', header: 'Payable', label: 'Payable', align: 'right', sortValue: (c) => c.payables_paise ?? 0, priority: 3, cell: (c) => <Money paise={c.payables_paise} /> },
      { key: 'tds', header: 'TDS overdue', label: 'TDS overdue', align: 'right', sortValue: (c) => c.tds_overdue_paise ?? 0, priority: 3, cell: (c) => c.tds_overdue_paise ? <span className="num text-destructive" title={formatPaise(c.tds_overdue_paise)}>{formatCompact(c.tds_overdue_paise)}</span> : <span className="text-faint">—</span> },
    ],
    [],
  )

  const open = (c: PortfolioClient) => {
    const target = nextTarget(c.next_step.code)
    void navigate({ to: target.to, params: { clientId: c.id }, search: target.search as never })
  }
  return (
    <DashCard
      title="How is each client doing?"
      hint="Select a client to continue its next piece of work. Click a column heading to sort."
      state={state === 'ready' && rows.length === 0 ? 'empty' : state}
      empty="No clients yet. Add a client and upload its bank statement to see its books here."
      skeleton="h-64"
    >
      {data && !data.detailed && <p className="mb-3 rounded-lg border bg-surface-2 px-4 py-3 text-sm text-muted-foreground">This firm has many clients, so only the stage and next step are worked out for each here. Open a client for its full picture.</p>}
      <DataTable caption="How each client is doing" columns={columns} rows={rows} rowKey={(c) => c.id} onRowClick={open} defaultSort={{ key: 'client', dir: 'asc' }} />
    </DashCard>
  )
}
