// GST reconciliation under "All clients": one row per client with its GSTINs and its latest run.
//
// The firm overview lists the clients; each row then asks for that client's own runs (one request
// per client, shared by the cells of the row). The API does not say how many differences a run has
// open without opening the run, so that figure lives on the run page, not here.

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { Search } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { gstRuns } from '@/api/queries/gst'
import { firmOverview } from '@/api/queries/overview'
import type { GstRun, OverviewClient } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { DataTable, type Column } from '@/components/ui/table'
import { usePageTitle } from '@/lib/title'
import { gstinsOf, latestRun, periodName } from './logic'

const none = <span className="text-faint">None yet</span>

/** What a row shows about a client's runs; `children` gets the runs once they are in. */
function Runs({ clientId, children }: { clientId: string; children: (runs: GstRun[]) => ReactNode }) {
  const runs = useQuery(gstRuns(clientId))
  if (runs.isLoading) return <span className="skeleton inline-block h-3 w-20 align-middle" aria-hidden />
  if (runs.error || !runs.data) return <span className="text-muted-foreground">Not available</span>
  return <>{children(runs.data)}</>
}

export function GstLanding() {
  usePageTitle('GST reconciliation')
  const overview = useQuery(firmOverview())
  const navigate = useNavigate()
  const { fy } = useSearch({ strict: false }) as { fy?: number }
  const [term, setTerm] = useState('')

  const rows = useMemo(() => {
    const t = term.trim().toLowerCase()
    return overview.data?.clients.filter((c) => !t || c.name.toLowerCase().includes(t))
  }, [overview.data, term])

  const search = (fy ? { fy } : {}) as never
  const open = (c: OverviewClient) => void navigate({ to: '/clients/$clientId/gst' as never, params: { clientId: c.id } as never, search })

  const columns: Column<OverviewClient>[] = [
    {
      key: 'client',
      header: 'Client',
      sortValue: (c) => c.name,
      cell: (c) => (
        <Link
          to={'/clients/$clientId/gst' as never}
          params={{ clientId: c.id } as never}
          search={search}
          className="block max-w-[28ch] truncate font-medium text-heading hover:underline"
          title={c.name}
          onClick={(e) => e.stopPropagation()}
        >
          {c.name}
        </Link>
      ),
    },
    {
      key: 'gstins',
      header: 'GSTINs with a run',
      priority: 2,
      cell: (c) => <Runs clientId={c.id}>{(runs) => (runs.length ? <span className="num">{gstinsOf(runs).join(', ')}</span> : none)}</Runs>,
    },
    {
      key: 'latest',
      header: 'Latest run',
      cell: (c) => (
        <Runs clientId={c.id}>
          {(runs) => {
            const run = latestRun(runs)
            return run ? <span>{periodName(run.period_start)}</span> : none
          }}
        </Runs>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (c) => (
        <Runs clientId={c.id}>
          {(runs) => {
            const run = latestRun(runs)
            if (!run) return <Badge tone="neutral">No run yet</Badge>
            return run.status === 'signed_off' ? <Badge tone="done">Signed off</Badge> : <Badge tone="attention">Draft</Badge>
          }}
        </Runs>
      ),
    },
    {
      key: 'open',
      header: <span className="sr-only">Action</span>,
      align: 'right',
      priority: 2,
      cell: (c) => (
        <Link
          to={'/clients/$clientId/gst' as never}
          params={{ clientId: c.id } as never}
          search={search}
          className="font-medium text-link hover:underline"
          onClick={(e) => e.stopPropagation()}
          aria-label={`Open GST reconciliation for ${c.name}`}
        >
          Open
        </Link>
      ),
    },
  ]

  return (
    <div className="grid gap-4">
      <PageHeader title="GST reconciliation" description="Match each month’s purchase register against GSTR-2B, decide the differences, and sign the month off." className="mb-0" />
      <div className="relative w-full max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input aria-label="Search clients" placeholder="Search clients" className="pl-9" value={term} onChange={(e) => setTerm(e.target.value)} />
      </div>
      {overview.error ? (
        <ErrorState error={overview.error} retry={() => void overview.refetch()} />
      ) : (
        <DataTable
          caption="Clients, GST reconciliation"
          columns={columns}
          rows={rows}
          loading={overview.isLoading}
          rowKey={(c) => c.id}
          onRowClick={open}
          defaultSort={{ key: 'client', dir: 'asc' }}
          empty={
            overview.data?.clients.length ? (
              <EmptyState title={`No client matches “${term.trim()}”`}>Check the spelling, or search for part of the name.</EmptyState>
            ) : (
              <EmptyState title="No clients yet">
                <Link to="/clients" className="text-link underline">
                  Add the first client
                </Link>{' '}
                to start.
              </EmptyState>
            )
          }
        />
      )}
      <p className="text-[13px] text-muted-foreground">Choose a client to open its GSTINs and runs. The number of differences still open is on each run.</p>
    </div>
  )
}
