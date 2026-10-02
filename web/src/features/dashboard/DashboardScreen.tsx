import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  FileUp,
  RefreshCw,
  Users,
} from 'lucide-react'
import { useMemo } from 'react'
import { firmOverview } from '@/api/queries/overview'
import { teamEvents } from '@/api/queries/team'
import type { FirmOverview, OverviewClient } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { StatCard, StatGrid } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/table'
import { formatDateLong, formatDateTime, plural } from '@/lib/format'
import { describeEvent } from '@/lib/team'
import { hasWork, needsAttention, nextTarget, STAGES, STAGE_LABEL, STAGE_TONE } from '@/lib/overview'
import { usePageTitle } from '@/lib/title'
import { ThisPeriod } from '@/features/work/MeasuredFigures'
import { useSession } from '@/session/session'

const LIVE_REFRESH_MS = 15_000

export function DashboardScreen() {
  usePageTitle('Dashboard')
  const { me, can } = useSession()
  const queryClient = useQueryClient()
  const overview = useQuery({ ...firmOverview(), refetchInterval: LIVE_REFRESH_MS, refetchIntervalInBackground: false })
  const updated = overview.dataUpdatedAt ? new Date(overview.dataUpdatedAt) : null
  const localNow = new Date()
  const localDate = `${localNow.getFullYear()}-${String(localNow.getMonth() + 1).padStart(2, '0')}-${String(localNow.getDate()).padStart(2, '0')}`
  const today = formatDateLong(localDate)
  const header = <PageHeader title="Dashboard" description={`${me?.firm?.name ?? 'Your firm'} · ${today}`} />
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['clients', 'overview'] })

  if (overview.error) {
    return <>{header}<ErrorState error={overview.error} retry={() => void overview.refetch()} /></>
  }
  if (overview.isLoading || !overview.data) {
    return <>{header}<div aria-busy="true" aria-live="polite" className="grid gap-4"><span className="sr-only">Loading the dashboard</span><StatGrid aria-hidden>{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-24 rounded-lg" />)}</StatGrid><div className="skeleton h-64 rounded-lg" aria-hidden /></div></>
  }

  const { totals, by_stage, clients } = overview.data
  if (totals.clients === 0) {
    return <>{header}<EmptyState title="No clients yet" action={can('client.create') && <Button asChild><Link to="/clients"><FileUp /> Add your first client</Link></Button>}>A client is one set of books. Add one, then upload its bank statement.</EmptyState></>
  }

  const withWork = clients.filter(hasWork).length
  const noLead = clients.filter((c) => !c.lead).length
  const placing = clients.filter((c) => c.unresolved > 0).length
  const posting = clients.filter((c) => c.pending_approval > 0).length
  const notStarted = by_stage.no_statements
  const actionClients = clients.filter((c) => c.unresolved || c.pending_approval || c.review_pending || c.ai_unchecked || !c.lead || c.months_missing.length)
  const openItems = totals.unresolved + totals.pending_approval + totals.review_pending + totals.ai_unchecked + totals.assistant_waiting

  return (
    <div className="grid gap-6 [&>*]:min-w-0">
      {header}
      <section aria-label="Live firm status" className="overflow-hidden rounded-xl border bg-card shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
          <div className="flex items-center gap-2.5">
            <span className="relative flex size-2.5" aria-hidden="true"><span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-50" /><span className="relative inline-flex size-2.5 rounded-full bg-success" /></span>
            <span className="text-sm font-semibold text-heading">Live operations</span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">Auto-refreshes every 15 sec</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{updated ? `Updated ${formatDateTime(updated.toISOString())}` : 'Waiting for first update'}</span>
            <Button variant="ghost" size="sm" onClick={refresh} disabled={overview.isFetching} aria-label="Refresh dashboard data">
              <RefreshCw className={overview.isFetching ? 'animate-spin' : ''} /> Refresh
            </Button>
          </div>
        </div>
        <div className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(19rem,1fr)]">
          <div className="grid content-center gap-2">
            <p className="text-xs font-medium uppercase tracking-[0.13em] text-muted-foreground">Your firm, right now</p>
            <h2 className="text-2xl font-semibold tracking-tight text-heading sm:text-3xl">
              {openItems > 0 ? `${openItems} items in the live queues` : 'The work queues are clear'}
            </h2>
            <p className="max-w-xl text-sm text-muted-foreground">
              {plural(totals.clients, 'client')} in view · {plural(withWork, 'client')} with operational work waiting. Counts update automatically while this page is open.
            </p>
            <Link to="/pipeline" className="mt-1 inline-flex w-fit items-center gap-2 text-sm font-medium text-link hover:underline">Open the work pipeline <ArrowRight className="size-4" /></Link>
          </div>
          <QueueMix unresolved={totals.unresolved} posting={totals.pending_approval} review={totals.review_pending} unchecked={totals.ai_unchecked} waiting={totals.assistant_waiting} />
        </div>
      </section>

      <section aria-label="Live workload" className="grid gap-3">
        <div className="flex items-center gap-2"><Activity className="size-4 text-muted-foreground" /><h2 className="text-sm font-semibold text-heading">Work waiting now</h2></div>
        <StatGrid>
          <StatCard label="Rows to place" value={totals.unresolved} note={totals.unresolved ? `Across ${plural(placing, 'client')}` : 'No rows need a ledger'} to="/pipeline" tone={totals.unresolved ? 'attention' : 'plain'} />
          <StatCard label="Ready to post" value={totals.pending_approval} note={totals.pending_approval ? `Across ${plural(posting, 'client')}` : 'No approvals waiting'} to="/pipeline" tone={totals.pending_approval ? 'attention' : 'plain'} />
          <StatCard label="Awaiting sign-off" value={totals.review_pending} note="Books sent for senior review" to="/pipeline" tone={totals.review_pending ? 'attention' : 'plain'} />
          <StatCard label="Assistant queue" value={totals.assistant_waiting} note={`${totals.ai_unchecked} assistant ${totals.ai_unchecked === 1 ? 'entry' : 'entries'} also need checking`} to="/bank" tone={totals.assistant_waiting || totals.ai_unchecked ? 'attention' : 'plain'} />
        </StatGrid>
      </section>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(18rem,0.8fr)]">
        <section aria-labelledby="flow-title" className="grid gap-3 rounded-xl border bg-card p-5">
          <div className="flex items-start justify-between gap-3">
            <div><h2 id="flow-title" className="text-[15px] font-semibold text-heading">Client workflow</h2><p className="mt-1 text-xs text-muted-foreground">How the active client work is distributed across the books process.</p></div>
            <Badge tone="neutral">{plural(totals.clients, 'client')}</Badge>
          </div>
          <WorkflowVisual byStage={by_stage} />
          <div className="flex flex-wrap gap-x-4 gap-y-2 border-t pt-3 text-xs text-muted-foreground">
            <span>{plural(notStarted, 'client')} without a statement</span><span>{totals.months_missing} missing statement months</span><span>{noLead} without a Senior CA</span>
          </div>
        </section>
        <AttentionSummary clients={clients} actionClients={actionClients.length} />
      </div>

      {can('team.view') && <ThisPeriod />}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <NeedsAttention clients={clients} />
        {can('team.view') && <RecentActivity />}
      </div>
    </div>
  )
}

function QueueMix({ unresolved, posting, review, unchecked, waiting }: { unresolved: number; posting: number; review: number; unchecked: number; waiting: number }) {
  const items = [
    { label: 'Place a ledger', value: unresolved, color: 'bg-accent-foreground', text: 'text-accent-foreground' },
    { label: 'Ready to post', value: posting, color: 'bg-info', text: 'text-info' },
    { label: 'Senior sign-off', value: review, color: 'bg-primary', text: 'text-primary' },
    { label: 'Check assistant entries', value: unchecked, color: 'bg-destructive', text: 'text-destructive' },
    { label: 'Assistant reading', value: waiting, color: 'bg-success', text: 'text-success' },
  ]
  const total = items.reduce((sum, item) => sum + item.value, 0)
  return (
    <div className="rounded-lg bg-muted/50 p-4">
      <div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold text-heading">Queue mix</h3><span className="num text-xs text-muted-foreground">{total} open items</span></div>
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={items.map((item) => `${item.value} ${item.label}`).join(', ')}>
        {items.map((item) => <span key={item.label} className={`${item.color} transition-[width] duration-500`} style={{ width: `${total ? (item.value / total) * 100 : 0}%` }} />)}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-2">
        {items.map((item) => <li key={item.label} className="flex min-w-0 items-center gap-2 text-xs"><span className={`size-2 shrink-0 rounded-full ${item.color}`} /><span className="min-w-0 flex-1 truncate text-muted-foreground">{item.label}</span><strong className={`num ${item.text}`}>{item.value}</strong></li>)}
      </ul>
    </div>
  )
}

function WorkflowVisual({ byStage }: { byStage: FirmOverview['by_stage'] }) {
  const total = Object.values(byStage).reduce((sum, count) => sum + count, 0)
  return (
    <div className="grid gap-3" role="img" aria-label={STAGES.map((stage) => `${STAGE_LABEL[stage]}: ${byStage[stage]}`).join(', ')}>
      <div className="flex h-3 overflow-hidden rounded-full bg-muted">
        {STAGES.map((stage) => <span key={stage} className={`transition-[width] duration-500 ${stage === 'signed_off' ? 'bg-success' : stage === 'in_review' ? 'bg-primary' : stage === 'ready_for_review' || stage === 'ready_to_post' ? 'bg-info' : stage === 'needs_ledger' ? 'bg-accent-foreground' : 'bg-muted-foreground/30'}`} style={{ width: `${total ? (byStage[stage] / total) * 100 : 0}%` }} />)}
      </div>
      <div className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
        {STAGES.map((stage, index) => <div key={stage} className="flex items-center gap-3">
          <span className={`grid size-8 shrink-0 place-items-center rounded-lg text-xs font-semibold ${STAGE_TONE[stage] === 'attention' ? 'bg-accent text-accent-foreground' : stage === 'signed_off' ? 'bg-success-bg text-success' : 'bg-muted text-muted-foreground'}`}>{String(index + 1).padStart(2, '0')}</span>
          <span className="min-w-0 flex-1"><span className="block truncate text-xs text-muted-foreground">{STAGE_LABEL[stage]}</span><span className="num text-lg font-semibold text-heading">{byStage[stage]}</span></span>
        </div>)}
      </div>
    </div>
  )
}

function AttentionSummary({ clients, actionClients }: { clients: OverviewClient[]; actionClients: number }) {
  const rows = [
    { label: 'Client has rows to place', count: clients.filter((c) => c.unresolved > 0).length, tone: 'bg-accent-foreground' },
    { label: 'Client has items to post', count: clients.filter((c) => c.pending_approval > 0).length, tone: 'bg-info' },
    { label: 'Client has missing months', count: clients.filter((c) => c.months_missing.length > 0).length, tone: 'bg-destructive' },
    { label: 'Client needs a Senior CA', count: clients.filter((c) => !c.lead).length, tone: 'bg-primary' },
  ]
  const max = Math.max(...rows.map((r) => r.count), 1)
  return (
    <section aria-labelledby="attention-summary" className="grid gap-4 rounded-xl border bg-card p-5">
      <div className="flex items-start justify-between gap-2"><div><h2 id="attention-summary" className="text-[15px] font-semibold text-heading">Attention map</h2><p className="mt-1 text-xs text-muted-foreground">Clients with work or a visible setup gap.</p></div><span className="grid size-9 place-items-center rounded-lg bg-accent text-accent-foreground"><AlertTriangle className="size-4" /></span></div>
      <div className="grid gap-3">
        {rows.map((row) => <div key={row.label} className="grid gap-1.5"><div className="flex justify-between gap-3 text-xs"><span className="text-muted-foreground">{row.label}</span><strong className="num text-heading">{row.count}</strong></div><div className="h-2 overflow-hidden rounded-full bg-muted"><div className={`h-full rounded-full ${row.tone} transition-[width] duration-500`} style={{ width: `${row.count / max * 100}%` }} /></div></div>)}
      </div>
      <Link to="/pipeline" className="flex items-center justify-between rounded-lg border px-3 py-2.5 text-sm hover:bg-hover"><span><strong className="num text-heading">{actionClients}</strong><span className="ml-2 text-muted-foreground">clients with an action or issue</span></span><ArrowRight className="size-4 text-muted-foreground" /></Link>
    </section>
  )
}

function NeedsAttention({ clients }: { clients: OverviewClient[] }) {
  const navigate = useNavigate()
  const rows = useMemo(() => needsAttention(clients), [clients])
  const columns: Column<OverviewClient>[] = [
    { key: 'client', header: 'Client', cell: (c) => <Link to="/clients/$clientId" params={{ clientId: c.id }} className="block max-w-[26ch] truncate font-medium text-heading hover:underline" title={c.name} onClick={(e) => e.stopPropagation()}>{c.name}</Link> },
    { key: 'waiting', header: 'Next work', cell: (c) => <span className="num">{c.unresolved > 0 && <span className="text-accent-foreground">{c.unresolved} to place</span>}{c.unresolved > 0 && c.pending_approval > 0 && <span className="text-faint"> · </span>}{c.pending_approval > 0 && <span>{c.pending_approval} ready</span>}{!hasWork(c) && c.review_pending && <span>Sent for review</span>}{!hasWork(c) && !c.review_pending && c.ai_unchecked > 0 && <span>{c.ai_unchecked} assistant {c.ai_unchecked === 1 ? 'entry' : 'entries'} unchecked</span>}{!hasWork(c) && !c.review_pending && !c.ai_unchecked && c.months_missing.length > 0 && <span>{c.months_missing.length} missing {c.months_missing.length === 1 ? 'month' : 'months'}</span>}</span> },
    { key: 'lead', header: 'Senior CA', priority: 2, cell: (c) => c.lead ? <span className="text-muted-foreground">{c.lead.name}</span> : <Badge tone="attention">Not assigned</Badge> },
  ]
  const open = (c: OverviewClient) => { const target = nextTarget(c.next_step.code); void navigate({ to: target.to, params: { clientId: c.id }, search: target.search as never }) }
  return <section aria-labelledby="needs" className="grid gap-3"><div className="flex items-baseline justify-between gap-3"><div><h2 id="needs" className="text-[15px] font-semibold text-heading">Clients needing a next step</h2><p className="mt-1 text-xs text-muted-foreground">Select a client to continue its next piece of work.</p></div><Link to="/clients" className="text-[13px] text-link underline underline-offset-2">All clients</Link></div><DataTable caption="Clients needing a next step" columns={columns} rows={rows} rowKey={(c) => c.id} onRowClick={open} empty={<EmptyState title="Nothing needs a next step">Every row is placed and posted, and nothing is waiting for a decision.</EmptyState>} /></section>
}

function RecentActivity() {
  const events = useQuery({ ...teamEvents(), refetchInterval: LIVE_REFRESH_MS, refetchIntervalInBackground: false })
  const rows = events.data?.results.slice(0, 6) ?? []
  return <section aria-labelledby="recent" className="grid gap-3"><div className="flex items-baseline justify-between gap-3"><div><h2 id="recent" className="text-[15px] font-semibold text-heading">Team activity</h2><p className="mt-1 text-xs text-muted-foreground">Recent assignment and team changes.</p></div><Link to="/settings/team" className="text-[13px] text-link underline underline-offset-2">Team & roles</Link></div>{events.isLoading ? <div className="skeleton h-24 rounded-lg" aria-busy="true" /> : events.error ? <ErrorState error={events.error} retry={() => void events.refetch()} /> : rows.length === 0 ? <p className="text-sm text-muted-foreground">Nothing has changed yet.</p> : <ul className="divide-y rounded-lg border bg-card text-sm">{rows.map((event) => <li key={event.id} className="flex gap-3 px-4 py-3"><span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground"><Users className="size-3.5" /></span><span className="min-w-0 flex-1"><span className="block">{describeEvent(event)}</span><span className="mt-0.5 block text-xs text-muted-foreground">{formatDateTime(event.at)}</span></span></li>)}</ul>}</section>
}
