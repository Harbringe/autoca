// The cards that read the work endpoints: the weekly flow, what each person has on, and a person's own work.
// Everything is a count of work. People are listed by name and never ranked, scored or compared.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo } from 'react'
import { firmPeople, myWork, workFlow } from '@/api/queries/dashboard'
import type { MyWork, NextTask, PersonWork } from '@/api/types'
import { DashCard } from '@/components/ca/DashCard'
import { KpiCard } from '@/components/ca/KpiCard'
import { DailyBars } from '@/components/charts/DailyBars'
import { DonutLegend } from '@/components/charts/DonutLegend'
import { FlowChart } from '@/components/charts/FlowChart'
import { ProgressBar } from '@/components/charts/ProgressBar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable, type Column } from '@/components/ui/table'
import { formatDate, plural } from '@/lib/format'
import { pct } from '@/lib/pct'

/** "Is work being finished?": rows received and entries finished each week, over twelve weeks. */
export function WorkFlowCard({ title = 'Is work getting done?' }: { title?: string }) {
  const q = useQuery(workFlow())
  const empty = q.data && q.data.totals.received === 0 && q.data.totals.finished === 0
  return (
    <DashCard
      title={title}
      hint={q.data?.scope === 'team' ? 'For your clients, the last 12 weeks.' : 'Across the firm, the last 12 weeks.'}
      state={q.isLoading ? 'loading' : q.error ? 'error' : empty ? 'empty' : 'ready'}
      error={q.error}
      onRetry={() => void q.refetch()}
      empty="No bank rows arrived and no entries were finished in this period."
      skeleton="h-56"
    >
      {q.data && <FlowChart flow={q.data} />}
    </DashCard>
  )
}

const ROLE_WORD: Record<string, string> = { FIRM_ADMIN: 'Firm owner', SENIOR_CA: 'Senior CA', STAFF: 'Staff', READ_ONLY: 'Read only' }

/** Finished against what is still open, on a person's own work: a share of their own, never compared with anyone. */
function OwnShare({ finished, open }: { finished: number; open: number }) {
  const total = finished + open
  if (total === 0) return <span className="text-faint">—</span>
  return (
    <span className="flex min-w-24 items-center gap-2">
      <ProgressBar value={finished} max={total} label={`${finished} finished and ${open} open`} className="w-16" />
      <span className="num text-xs text-muted-foreground">{pct(finished, total)}%</span>
    </span>
  )
}

/**
 * "What does each person have on?": five counts per person, alphabetical. Counts of work, not a rating of people.
 * Asked only by owners and seniors; the server refuses everyone else, so the card is not rendered for them.
 */
export function PeopleCard({ title = 'What does each person have on?' }: { title?: string }) {
  const q = useQuery(firmPeople())
  const rows = q.data?.people ?? []
  const detailed = q.data?.detailed ?? true
  const columns: Column<PersonWork>[] = useMemo(
    () => [
      { key: 'name', header: 'Person', label: 'Person', sortValue: (p) => p.name.toLowerCase(), sticky: true, cell: (p) => <span className="block max-w-[24ch] truncate font-medium text-heading" title={p.name}>{p.name}</span> },
      { key: 'role', header: 'Role', label: 'Role', priority: 3, sortValue: (p) => p.role, cell: (p) => <Badge tone="neutral">{ROLE_WORD[p.role] ?? p.role}</Badge> },
      { key: 'clients', header: 'Clients', label: 'Clients', align: 'right', sortValue: (p) => p.assigned_clients, cell: (p) => <span className="num">{p.assigned_clients}</span> },
      { key: 'open', header: 'Open', label: 'Open', align: 'right', sortValue: (p) => p.open_items, cell: (p) => <span className="num">{p.open_items}</span> },
      { key: 'done', header: 'Finished', label: 'Finished', align: 'right', sortValue: (p) => p.finished_in_period, cell: (p) => <span className="num">{p.finished_in_period}</span> },
      { key: 'late', header: 'Late', label: 'Late', align: 'right', priority: 2, sortValue: (p) => p.overdue, cell: (p) => (detailed ? <span className={p.overdue ? 'num text-destructive' : 'num'}>{p.overdue}</span> : <span className="text-faint">—</span>) },
      { key: 'wait', header: 'Waiting on others', label: 'Waiting on others', align: 'right', priority: 3, sortValue: (p) => p.waiting_on_others, cell: (p) => <span className="num">{p.waiting_on_others}</span> },
      { key: 'share', header: 'Own share done', label: 'Own share done', priority: 2, sortValue: (p) => pct(p.finished_in_period, p.finished_in_period + p.open_items), cell: (p) => <OwnShare finished={p.finished_in_period} open={p.open_items} /> },
    ],
    [detailed],
  )
  return (
    <DashCard
      title={title}
      hint="Counts of work in name order. This month for finished; right now for the rest."
      state={q.isLoading ? 'loading' : q.error ? 'error' : rows.length === 0 ? 'empty' : 'ready'}
      error={q.error}
      onRetry={() => void q.refetch()}
      empty="Nobody has been added to your team yet."
      skeleton="h-48"
    >
      {!detailed && <p className="mb-3 text-[13px] text-muted-foreground">This firm has many clients, so lateness is not worked out here.</p>}
      <DataTable caption="What each person has on" columns={columns} rows={rows} rowKey={(p) => p.member_id} defaultSort={{ key: 'name', dir: 'asc' }} />
      <p className="mt-3 text-xs text-muted-foreground">Counts of work, not a rating of people.</p>
    </DashCard>
  )
}

// ---------------------------------------------------------------------------
// A person's own work (Staff)
// ---------------------------------------------------------------------------

export function useMyWork() {
  return useQuery(myWork())
}

export function MyKpis({ data, loading }: { data: MyWork | undefined; loading: boolean }) {
  const d = data
  return (
    <div className="col-span-12 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <KpiCard loading={loading} label="Work given to me" value={d?.assigned_clients ?? 0} note={d ? plural(d.assigned_clients, 'client') + ' assigned to me' : undefined} to="/clients" />
      <KpiCard loading={loading} label="Still to do" value={d?.open_items ?? 0} note="Entries to sort or record, right now" tone={d?.open_items ? 'attention' : 'plain'} to="/pipeline" />
      <KpiCard loading={loading} label="Late" value={d?.overdue ?? 0} note={d?.overdue ? 'Something is overdue on my clients' : 'Nothing is late'} tone={d?.overdue ? 'attention' : 'plain'} to="/alerts" />
      <KpiCard loading={loading} label="Finished this month" value={d?.finished_in_period ?? 0} note="Entries I posted" />
    </div>
  )
}

function TaskRow({ t, first }: { t: NextTask; first: boolean }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 first:pt-0">
      <div className="min-w-0 flex-1 basis-52">
        <div className="truncate text-sm font-semibold text-heading" title={t.client_name}>{t.client_name}</div>
        <div className="text-[13px] text-muted-foreground">{t.title}</div>
        {t.due && <div className="text-xs text-muted-foreground">Due {formatDate(t.due)}</div>}
        {t.severity === 'critical' && <div className="text-xs text-destructive">Late</div>}
      </div>
      <Button asChild size="sm" variant={first ? 'primary' : 'secondary'} className="max-sm:min-h-11 max-sm:w-full">
        <Link to={t.to as never} search={t.search as never} aria-label={`Open: ${t.title}, ${t.client_name}`}>Open</Link>
      </Button>
    </li>
  )
}

/** "What should I do next?": the server's next tasks, late ones first, each opening where it is done. */
export function NextTasksCard({ data, loading, error }: { data: MyWork | undefined; loading: boolean; error?: unknown }) {
  const tasks = data?.next_tasks ?? []
  return (
    <DashCard
      title="What should I do next?"
      hint="Late things first. Each button opens the exact screen."
      state={loading ? 'loading' : error ? 'error' : tasks.length === 0 ? 'empty' : 'ready'}
      error={error}
      empty="Nothing to do. Check back after your Senior CA assigns work."
      skeleton="h-56"
    >
      <ol className="divide-y">
        {tasks.map((t, i) => (
          <TaskRow key={`${t.client}-${t.to}-${i}`} t={t} first={i === 0} />
        ))}
      </ol>
    </DashCard>
  )
}

/** "How much of my work is done?": finished this period against what is still open and what waits on others. */
export function MyProgressCard({ data, loading }: { data: MyWork | undefined; loading: boolean }) {
  const finished = data?.finished_in_period ?? 0
  const open = data?.open_items ?? 0
  const waiting = data?.waiting ?? 0
  const total = finished + open + waiting
  return (
    <DashCard
      title="How much of my work is done?"
      hint="Finished this month, still open, and waiting on someone else."
      state={loading ? 'loading' : total === 0 ? 'empty' : 'ready'}
      empty="No work is assigned to you yet, so there is nothing to measure."
      skeleton="h-44"
    >
      <DonutLegend
        rows={[
          { key: 'done', label: 'Finished', count: finished, color: 'var(--chart-1)' },
          { key: 'open', label: 'Still open', count: open, color: 'var(--chart-2)' },
          { key: 'wait', label: 'Waiting on others', count: waiting, color: 'var(--chart-muted)' },
        ]}
        centerValue={`${pct(finished, total)}%`}
        centerLabel="done"
        summary={`${finished} finished, ${open} still open and ${waiting} waiting on others: ${pct(finished, total)}% done.`}
        caption="My work by state"
      />
    </DashCard>
  )
}

/** "How much did I finish each day?": one bar a day of the period. */
export function DailyFinishedCard({ data, loading }: { data: MyWork | undefined; loading: boolean }) {
  const days = data?.daily ?? []
  const total = days.reduce((n, d) => n + d.finished, 0)
  return (
    <DashCard
      title="How much did I finish each day?"
      hint="Entries I posted, this month."
      state={loading ? 'loading' : total === 0 ? 'empty' : 'ready'}
      empty="You have not finished anything yet this month."
      skeleton="h-44"
    >
      <DailyBars days={days} />
    </DashCard>
  )
}

/** "Which of my clients have work open?": the clients the server lists, in name order, with their open counts. */
export function MyWorkClientsCard({ data, loading }: { data: MyWork | undefined; loading: boolean }) {
  const rows = data?.clients ?? []
  const max = Math.max(1, ...rows.map((r) => r.open_items))
  return (
    <DashCard
      title="Which of my clients have work open?"
      hint="In name order. The bar is how many things are open on it."
      state={loading ? 'loading' : rows.length === 0 ? 'empty' : 'ready'}
      empty="You are not on any client yet. Ask your Senior CA."
      to="/clients"
      seeAll="All my clients"
      skeleton="h-48"
    >
      <ul className="grid gap-3">
        {rows.slice(0, 8).map((c) => (
          <li key={c.id}>
            <Link to="/clients/$clientId" params={{ clientId: c.id }} className="grid gap-1 rounded-md py-1 hover:bg-hover">
              <span className="flex items-baseline justify-between gap-3 text-sm">
                <span className="min-w-0 truncate font-medium text-heading" title={c.name}>{c.name}</span>
                <span className="num shrink-0 text-[13px] text-muted-foreground">{c.open_items === 0 ? 'Nothing open' : plural(c.open_items, 'thing')}</span>
              </span>
              <ProgressBar value={c.open_items} max={max} label={`${c.open_items} open on ${c.name}`} tone="accent" />
            </Link>
          </li>
        ))}
      </ul>
      {rows.length > 8 && <p className="mt-2 text-[13px] text-muted-foreground">And {rows.length - 8} more.</p>}
    </DashCard>
  )
}
