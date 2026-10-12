// The firm's clients, one line each: who is in charge, how far the statements run, what is waiting,
// and the next thing to do. Comfortable density, because a CA scans this list rather than works in it.
//
// The list (paging, search, FY start) comes from /clients/; where each client stands comes from the
// one firm overview request, joined by id, so a page costs two requests however many clients it has.

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable, type Column } from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { clientsList } from '@/api/queries/clients'
import { firmOverview } from '@/api/queries/overview'
import type { Client, OverviewClient } from '@/api/types'
import { formatDate, plural } from '@/lib/format'
import { normaliseName } from '@/lib/names'
import { useHotkey } from '@/lib/hotkeys'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { NewClientDialog } from './NewClientDialog'
import { nextTarget, parseStage, STAGE_LABEL, STAGE_TONE } from '@/lib/overview'
import { barPercent, filterCounts, initials } from './clientsView'

const PAGE_SIZE = 50

/** Status as a soft pill: the shape and the words, no icon, as the list is read at a glance. */
const PILL = 'h-7 rounded-full px-3 text-[13px]'

type Filter = 'all' | 'mine' | 'unresolved' | 'ready' | 'unassigned'
const FILTERS: [Filter, string][] = [
  ['all', 'All'],
  ['mine', 'Mine'],
  ['unresolved', 'Needs a ledger'],
  ['ready', 'Ready to post'],
  ['unassigned', 'Not assigned'],
]

interface Row {
  client: Client
  loading: boolean
  latest: string | null
  unresolved: number
  ready: number
  /** Null until the overview has arrived, or for a client it does not list. */
  standing: OverviewClient | null
}

export function ClientsScreen() {
  const { can, me } = useSession()
  const [search, setSearch] = useState('')
  const [term, setTerm] = useState('')
  const [page, setPage] = useState(1)
  const [filter, setFilter] = useState<Filter>('all')
  const [creating, setCreating] = useState(false)
  const stage = parseStage((useSearch({ strict: false }) as { stage?: unknown }).stage)
  const navigate = useNavigate()

  useEffect(() => {
    const t = setTimeout(() => {
      setTerm(search.trim())
      setPage(1)
    }, 250)
    return () => clearTimeout(t)
  }, [search])

  const clients = useQuery(clientsList(term, page))
  const canCreate = can('client.create')
  useHotkey('n', 'New client', () => canCreate && setCreating(true), 'Clients')

  const overview = useQuery(firmOverview())
  const byId = useMemo(() => new Map(overview.data?.clients.map((c) => [c.id, c])), [overview.data])
  const list = clients.data?.results
  const rows: Row[] | undefined = useMemo(
    () =>
      list?.map((client) => {
        const o = byId.get(client.id) ?? null
        return {
          client,
          loading: overview.isLoading,
          latest: o?.last_statement_end ?? null,
          unresolved: o?.unresolved ?? 0,
          ready: o?.pending_approval ?? 0,
          standing: o,
        }
      }),
    [list, byId, overview.isLoading],
  )
  const shown = rows?.filter((r) => {
    if (stage && r.standing?.stage !== stage) return false
    if (filter === 'mine') return !!me?.membership_id && r.client.lead?.id === me.membership_id
    if (filter === 'unassigned') return !r.client.lead
    if (filter === 'unresolved') return r.unresolved > 0
    if (filter === 'ready') return r.ready > 0
    return true
  })

  const total = clients.data?.count ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  // Counts are read from the clients on this page, so they are only true when the whole list is on it.
  const wholeList = pages === 1 && !!rows && !overview.isLoading
  const counts = useMemo(
    () =>
      wholeList && rows
        ? filterCounts(rows.map((r) => ({ unresolved: r.unresolved, ready: r.ready, mine: !!me?.membership_id && r.client.lead?.id === me.membership_id, assigned: !!r.client.lead })))
        : null,
    [wholeList, rows, me?.membership_id],
  )
  const busiest = useMemo(() => Math.max(0, ...(rows ?? []).map((r) => r.unresolved + r.ready)), [rows])
  const withWork = rows?.filter((r) => r.unresolved + r.ready > 0).length ?? 0

  const columns: Column<Row>[] = [
    {
      key: 'client',
      header: 'Client',
      sortValue: (r) => r.client.name,
      cell: (r) => (
        <div className="flex min-w-0 items-center gap-3">
          <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted text-[13px] font-semibold text-muted-foreground">
            {initials(r.client.name)}
          </span>
          <div className="min-w-0">
            <Link to="/clients/$clientId" params={{ clientId: r.client.id }} className="block max-w-[34ch] truncate font-semibold text-heading hover:underline" title={r.client.name}>
              {normaliseName(r.client.name)}
            </Link>
            <span className="block text-xs text-muted-foreground">FY starts {formatDate(r.client.fy_start)}</span>
          </div>
        </div>
      ),
    },
    {
      key: 'lead',
      header: 'Senior CA',
      priority: 2,
      sortValue: (r) => r.client.lead?.name ?? '',
      cell: (r) => (r.client.lead ? <span className="text-muted-foreground">{r.client.lead.name}</span> : <Badge tone="attention" icon={false} className={PILL}>Not assigned</Badge>),
    },
    {
      key: 'stage',
      header: 'Stage',
      priority: 2,
      sortValue: (r) => r.standing?.stage ?? '',
      cell: (r) => (r.standing ? <Badge tone={r.standing.stage === 'ready_to_post' ? 'done' : STAGE_TONE[r.standing.stage]} icon={false} className={PILL}>{STAGE_LABEL[r.standing.stage]}</Badge> : <span className="text-faint">{r.loading ? '…' : '–'}</span>),
    },
    {
      key: 'waiting',
      header: 'Waiting',
      priority: 2,
      width: '15rem',
      sortValue: (r) => r.unresolved * 100_000 + r.ready,
      cell: (r) =>
        r.loading ? (
          <span className="text-faint">…</span>
        ) : r.unresolved || r.ready ? (
          <div className="grid gap-1.5">
            <span className="flex items-baseline gap-2">
              <span className="num text-lg font-semibold text-heading">{(r.unresolved + r.ready).toLocaleString('en-IN')}</span>
              <span className="text-xs text-muted-foreground">
                {r.unresolved > 0 && r.ready > 0 ? `${r.unresolved} to place · ${r.ready} ready` : r.unresolved > 0 ? `${r.unresolved.toLocaleString('en-IN')} to place` : `${r.ready.toLocaleString('en-IN')} ready`}
              </span>
            </span>
            <span aria-hidden className="block h-1.5 rounded-full bg-muted">
              <span
                className={cn('block h-1.5 rounded-full', r.unresolved > 0 ? 'bg-accent-foreground' : 'bg-primary')}
                style={{ width: `${barPercent(r.unresolved + r.ready, busiest)}%` }}
              />
            </span>
          </div>
        ) : (
          <span className="text-faint">Nothing</span>
        ),
    },
    { key: 'next', header: 'Next step', cell: (r) => <NextStepLink row={r} /> },
    {
      key: 'latest',
      header: 'Statements to',
      priority: 3,
      align: 'right',
      sortValue: (r) => r.latest ?? '',
      cell: (r) => (r.loading ? <span className="text-faint">…</span> : r.latest ? <span className="num font-mono">{formatDate(r.latest)}</span> : <span className="text-faint">None</span>),
    },
  ]

  return (
    <>
      <PageHeader
        title="Clients"
        description={
          clients.data
            ? wholeList && total > 0
              ? `${plural(total, 'client')}. ${withWork === 0 ? 'None has work waiting.' : `${withWork} ${withWork === 1 ? 'has' : 'have'} work waiting.`}${busiest > 0 && withWork > 1 ? ` ${busiest.toLocaleString('en-IN')} rows are waiting at one of them.` : ''}`
              : plural(total, 'client')
            : undefined
        }
        actions={
          canCreate && (
            <Button className="h-11 rounded-lg px-5" onClick={() => setCreating(true)}>
              New client
            </Button>
          )
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input aria-label="Search clients" placeholder="Search by name" className="h-11 rounded-lg pl-9" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
          {FILTERS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              className={cn(
                'h-9 rounded-full border px-4 text-[13px] font-medium',
                filter === id ? 'border-foreground bg-foreground text-background' : 'border-input bg-transparent text-foreground hover:bg-hover',
              )}
            >
              {label}
              {counts && <span className={cn('ml-1.5 tabular-nums', filter === id ? 'opacity-80' : 'text-muted-foreground')}>{counts[id]}</span>}
            </button>
          ))}
        </div>
      </div>

      {stage && (
        <p className="mb-4 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          Showing clients whose books are
          <span className="inline-flex items-center gap-1 rounded-md border bg-card py-0.5 pl-2.5 pr-1 font-medium text-heading">
            {STAGE_LABEL[stage]}
            <button type="button" aria-label="Show all clients" className="grid size-6 place-items-center rounded hover:bg-hover max-sm:size-11" onClick={() => void navigate({ to: '/clients', search: {} as never })}>
              <X className="size-3.5" />
            </button>
          </span>
        </p>
      )}

      {clients.error ? (
        <ErrorState error={clients.error} retry={() => void clients.refetch()} />
      ) : !clients.isPending && clients.data?.results.length === 0 ? (
        term ? (
          <EmptyState
            title={`No client matches “${term}”`}
            action={
              <Button variant="secondary" onClick={() => setSearch('')}>
                Clear search
              </Button>
            }
          >
            Check the spelling, or search for part of the name.
          </EmptyState>
        ) : canCreate ? (
          <EmptyState
            title="No clients yet"
            action={
              <Button onClick={() => setCreating(true)}>Add your first client</Button>
            }
          >
            A client is one set of books: its own chart of accounts, statements and financial year.
          </EmptyState>
        ) : (
          <EmptyState title="No clients assigned to you">You will see a client here once your senior CA assigns you to it.</EmptyState>
        )
      ) : (
        <>
          <DataTable
            caption="Clients"
            columns={columns}
            rows={shown}
            loading={clients.isPending}
            rowKey={(r) => r.client.id}
            defaultSort={{ key: 'client', dir: 'asc' }}
            roomy
            rowClassName={() => 'h-20'}
            onRowClick={(r) => void navigate({ to: '/clients/$clientId', params: { clientId: r.client.id } })}
            empty={
              <EmptyState title="No client fits that filter">
                {rows?.some((r) => r.loading) ? 'Still reading each client’s books.' : 'Try another filter, or show all clients.'}
              </EmptyState>
            }
          />
          <p className="mt-4 text-[13px] text-muted-foreground">Click a row to open that client. The teal link is the next piece of work.</p>
          {pages > 1 && (
            <div className="mt-3 flex items-center justify-between text-[13px] text-muted-foreground">
              <span>
                Page {page} of {pages}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      <NewClientDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}

const STEP_TONE = { upload: 'text-link', place: 'text-accent-foreground', post: 'text-link', sign_off: 'text-link', send_for_review: 'text-accent-foreground', none: 'text-success' } as const

/** The next step, linking straight to where it is done. */
function NextStepLink({ row }: { row: Row }) {
  const o = row.standing
  if (!o) return <span className="text-faint">{row.loading ? '…' : '–'}</span>
  const cls = cn('font-medium hover:underline', STEP_TONE[o.next_step.code])
  if (o.next_step.code === 'none') return <span className={cn('font-medium', STEP_TONE.none)} title={STAGE_LABEL[o.stage]}>{o.next_step.label}</span>
  const target = nextTarget(o.next_step.code)
  return (
    <Link to={target.to} params={{ clientId: row.client.id }} search={target.search as never} className={cls}>
      {o.next_step.label}
    </Link>
  )
}
