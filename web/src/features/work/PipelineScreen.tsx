// Work pipeline: where every client's books stand (Board), and who is in charge of each (Allocation).
//
// A column is a state the books are in, not a status a person sets, so cards do not drag. Each
// column is a plain list with a heading and a count, which is also the keyboard and screen-reader
// view. Stages and next steps come from the firm overview.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { firmOverview } from '@/api/queries/overview'
import { teamClients } from '@/api/queries/team'
import type { OverviewClient, Stage, TeamClient } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { People } from '@/features/clients/ClientTeamScreen'
import { TabNav } from '@/components/ui/tabs'
import { DataTable, type Column } from '@/components/ui/table'
import { formatDate, plural } from '@/lib/format'
import { nextTarget, STAGES, STAGE_HINT, STAGE_LABEL, STAGE_TONE } from '@/lib/overview'
import { usePageTitle } from '@/lib/title'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export type PipelineView = 'board' | 'allocation'

export function parsePipelineView(value: unknown): PipelineView {
  return value === 'allocation' ? 'allocation' : 'board'
}

export function PipelineScreen({ view }: { view: PipelineView }) {
  const { can } = useSession()
  usePageTitle('Work pipeline')
  const allocate = can('team.view')
  const shown: PipelineView = allocate ? view : 'board'
  return (
    <div className="grid gap-4">
      <PageHeader title="Work pipeline" description="Where each client’s books stand, and who is in charge." className="mb-0" />
      {allocate && (
        <TabNav
          label="Work pipeline views"
          items={[
            { to: '/pipeline', label: 'Board', search: { view: 'board' } },
            { to: '/pipeline', label: 'Allocation', search: { view: 'allocation' } },
          ]}
        />
      )}
      {shown === 'board' ? <Board /> : <Allocation />}
    </div>
  )
}

function Board() {
  const overview = useQuery(firmOverview())
  if (overview.error) return <ErrorState error={overview.error} retry={() => void overview.refetch()} />
  if (overview.isLoading || !overview.data) {
    return (
      <div aria-busy="true" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <span className="sr-only">Loading the pipeline</span>
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="skeleton h-40 rounded-lg" aria-hidden />
        ))}
      </div>
    )
  }
  const { clients, by_stage } = overview.data
  if (clients.length === 0) return <EmptyState title="No clients yet">Add a client from Clients and its books will appear here.</EmptyState>
  const inStage = (stage: Stage) => clients.filter((c) => c.stage === stage).sort((a, b) => a.name.localeCompare(b.name))
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {STAGES.map((stage) => (
        <section key={stage} aria-labelledby={`stage-${stage}`} className="rounded-lg border bg-surface-2 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 id={`stage-${stage}`} className="text-[13px] font-semibold text-heading">
              {STAGE_LABEL[stage]}
            </h2>
            <Badge tone={STAGE_TONE[stage]} aria-label={`${by_stage[stage]} clients`}>
              {by_stage[stage]}
            </Badge>
          </div>
          <p className="mb-2 text-xs text-muted-foreground">{STAGE_HINT[stage]}</p>
          {inStage(stage).length === 0 ? (
            <p className="rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">No clients here</p>
          ) : (
            <ul className="grid gap-2">
              {inStage(stage).map((c) => (
                <li key={c.id}>
                  <ClientCard client={c} />
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  )
}

function ClientCard({ client: c }: { client: OverviewClient }) {
  const target = nextTarget(c.next_step.code)
  return (
    <Link
      to={target.to}
      params={{ clientId: c.id }}
      search={target.search as never}
      className="block rounded-md border bg-card p-3 hover:bg-hover"
    >
      <span className="block truncate text-sm font-medium text-heading" title={c.name}>
        {c.name}
      </span>
      <span className="mt-0.5 block text-[13px] text-foreground">{c.next_step.label}</span>
      <span className={cn('mt-0.5 block text-xs', c.lead ? 'text-muted-foreground' : 'text-accent-foreground')}>
        {c.lead ? c.lead.name : 'No Senior CA'}
        {c.signed_off_through ? ` · signed off to ${formatDate(c.signed_off_through)}` : ''}
      </span>
    </Link>
  )
}

function Allocation() {
  const clients = useQuery(teamClients())
  const [open, setOpen] = useState<TeamClient | null>(null)
  if (clients.error) return <ErrorState error={clients.error} retry={() => void clients.refetch()} />
  const rows = clients.data?.results
  const canSet = clients.data?.can.set_lead ?? false
  const columns: Column<TeamClient>[] = [
    {
      key: 'client',
      header: 'Client',
      sortValue: (c) => c.name,
      cell: (c) => (
        <Link to="/clients/$clientId" params={{ clientId: c.id }} className="block max-w-[28ch] truncate font-medium text-heading hover:underline" title={c.name}>
          {c.name}
        </Link>
      ),
    },
    {
      key: 'lead',
      header: 'Senior CA',
      sortValue: (c) => c.lead?.name ?? '',
      cell: (c) => (c.lead ? c.lead.name : <Badge tone="attention">Not assigned</Badge>),
    },
    {
      key: 'team',
      header: 'Team',
      priority: 3,
      cell: (c) => <span className="block max-w-[32ch] truncate text-muted-foreground" title={c.team.map((p) => p.name).join(', ')}>{c.team.map((p) => p.name).join(', ') || 'Nobody assigned'}</span>,
    },
    {
      key: 'waiting',
      header: 'Waiting',
      align: 'right',
      priority: 2,
      sortValue: (c) => c.unresolved * 100_000 + c.pending_approval,
      cell: (c) =>
        c.unresolved || c.pending_approval ? (
          <span className="num">
            {c.unresolved > 0 && <span className="text-accent-foreground">{c.unresolved} to place</span>}
            {c.unresolved > 0 && c.pending_approval > 0 && <span className="text-faint"> · </span>}
            {c.pending_approval > 0 && <span>{c.pending_approval} ready</span>}
          </span>
        ) : (
          <span className="text-faint">Nothing</span>
        ),
    },
    {
      key: 'assign',
      header: <span className="sr-only">Assign</span>,
      align: 'right',
      cell: (c) => (
        <Button variant="ghost" size="sm" onClick={() => setOpen(c)} aria-label={`${canSet ? 'Assign people to' : 'See the team of'} ${c.name}`}>
          {canSet ? 'Assign' : 'Team'}
        </Button>
      ),
    },
  ]
  const without = rows?.filter((c) => !c.lead).length ?? 0
  return (
    <div className="grid gap-3">
      {rows && without > 0 && <p className="text-sm text-muted-foreground">{plural(without, 'client')} without a Senior CA. They sign off the books, so assign one first.</p>}
      <DataTable
        caption="Allocation: who is in charge of each client"
        columns={columns}
        rows={rows}
        loading={clients.isLoading}
        rowKey={(c) => c.id}
        defaultSort={{ key: 'client', dir: 'asc' }}
        empty={<EmptyState title="No clients yet">Add a client from Clients, then choose who is in charge.</EmptyState>}
      />
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>{open?.name}</DialogTitle>
            <DialogDescription>Who is in charge of this client and who works on it.</DialogDescription>
          </DialogHeader>
          {open && <People clientId={open.id} justCreated={false} />}
          {open && (
            <Link to="/clients/$clientId/team" params={{ clientId: open.id }} className="text-sm text-link underline">
              Open the client’s team and details page
            </Link>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
