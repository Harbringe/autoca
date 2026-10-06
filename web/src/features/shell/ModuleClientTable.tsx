// A client-scoped module opened under "All clients": one row per client with the columns that
// module cares about, from the one firm overview request. Picking a row opens the module for that
// client, on the same tab the sidebar would (Day Book, Statements, Trial Balance).

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { firmOverview } from '@/api/queries/overview'
import type { OverviewClient } from '@/api/types'
import { ModuleAlerts } from '@/features/alerts/AlertList'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { DataTable, type Column } from '@/components/ui/table'
import { formatDate, plural } from '@/lib/format'
import { MODULE_CLIENT_SCREEN, type ModuleId } from '@/lib/modules'
import { booksWord, monthsText } from '@/lib/overview'
import { usePageTitle } from '@/lib/title'

type LandingModule = 'bookkeeping' | 'bank' | 'reports'

const COPY: Record<LandingModule, { title: string; description: string }> = {
  bookkeeping: { title: 'Bookkeeping', description: 'Day Book, ledgers, parties and sign-off, one client at a time.' },
  bank: { title: 'Bank statements', description: 'Upload statements, place each row in a ledger, and post to the Day Book.' },
  reports: { title: 'Reports', description: 'Trial Balance, Profit & Loss, Balance Sheet and bank reconciliation.' },
}

const nil = <span className="text-faint">–</span>
const count = (n: number) => (n ? n : nil)

/** Where this module opens for a client: /clients/<id>/<screen>. */
const screenFor = (module: LandingModule) => MODULE_CLIENT_SCREEN[module as ModuleId] as string

export function ModuleClientTable({ module }: { module: LandingModule }) {
  const copy = COPY[module]
  usePageTitle(copy.title)
  const overview = useQuery(firmOverview())
  const navigate = useNavigate()
  const { fy } = useSearch({ strict: false }) as { fy?: number }
  const [term, setTerm] = useState('')
  const screen = screenFor(module)

  const rows = useMemo(() => {
    const t = term.trim().toLowerCase()
    return overview.data?.clients.filter((c) => !t || c.name.toLowerCase().includes(t))
  }, [overview.data, term])

  const open = (c: OverviewClient) => void navigate({ to: `/clients/${c.id}/${screen}` as never, search: (fy ? { fy } : {}) as never })
  const nameCell = (c: OverviewClient) => (
    <Link
      to={`/clients/${c.id}/${screen}` as never}
      search={(fy ? { fy } : {}) as never}
      className="block max-w-[28ch] truncate font-medium text-heading hover:underline"
      title={c.name}
      onClick={(e) => e.stopPropagation()}
    >
      {c.name}
    </Link>
  )
  const client: Column<OverviewClient> = { key: 'client', header: 'Client', sortValue: (c) => c.name, cell: nameCell }
  const lead: Column<OverviewClient> = {
    key: 'lead',
    header: 'Senior CA',
    priority: 2,
    sortValue: (c) => c.lead?.name ?? '',
    cell: (c) => (c.lead ? <span className="text-muted-foreground">{c.lead.name}</span> : <Badge tone="attention">Not assigned</Badge>),
  }
  const signedTo: Column<OverviewClient> = {
    key: 'signed',
    header: 'Signed off to',
    priority: 2,
    align: 'right',
    sortValue: (c) => c.signed_off_through ?? '',
    cell: (c) => (c.signed_off_through ? formatDate(c.signed_off_through) : <span className="text-faint">Not yet</span>),
  }

  const columns: Column<OverviewClient>[] =
    module === 'bookkeeping'
      ? [
          client,
          lead,
          {
            key: 'books',
            header: 'Books status',
            cell: (c) => {
              const w = booksWord(c)
              return <Badge tone={w.tone}>{w.label}</Badge>
            },
          },
          signedTo,
          {
            key: 'waiting',
            header: 'Entries waiting',
            align: 'right',
            priority: 2,
            sortValue: (c) => c.unresolved + c.pending_approval,
            cell: (c) => count(c.unresolved + c.pending_approval),
          },
          {
            key: 'unchecked',
            header: 'Assistant entries unchecked',
            align: 'right',
            priority: 3,
            sortValue: (c) => c.ai_unchecked,
            cell: (c) => count(c.ai_unchecked),
          },
        ]
      : module === 'bank'
        ? [
            client,
            {
              key: 'latest',
              header: 'Latest statement to',
              align: 'right',
              sortValue: (c) => c.last_statement_end ?? '',
              cell: (c) => (c.last_statement_end ? formatDate(c.last_statement_end) : <span className="text-faint">None</span>),
            },
            {
              key: 'missing',
              // The server looks inside each account's run of statements, not at the financial year.
              header: 'Months missing in the run',
              align: 'right',
              priority: 3,
              sortValue: (c) => c.months_missing.length,
              cell: (c) =>
                c.months_missing.length ? (
                  <span title={monthsText(c.months_missing)} className="text-accent-foreground">
                    {c.months_missing.length}
                  </span>
                ) : (
                  nil
                ),
            },
            { key: 'needs', header: 'Needs a ledger', align: 'right', sortValue: (c) => c.unresolved, cell: (c) => count(c.unresolved) },
            { key: 'ready', header: 'Ready to post', align: 'right', priority: 2, sortValue: (c) => c.pending_approval, cell: (c) => count(c.pending_approval) },
            {
              key: 'action',
              header: <span className="sr-only">Action</span>,
              align: 'right',
              priority: 2,
              cell: (c) => (
                <Link
                  to={'/clients/$clientId/statements' as never}
                  params={{ clientId: c.id } as never}
                  className="font-medium text-link hover:underline"
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`Upload a statement for ${c.name}`}
                >
                  Upload
                </Link>
              ),
            },
          ]
        : [
            client,
            signedTo,
            {
              key: 'prov',
              header: 'Provisional?',
              sortValue: (c) => c.unresolved + c.pending_approval,
              cell: (c) => {
                const n = c.unresolved + c.pending_approval
                return n ? <Badge tone="attention">Provisional, {plural(n, 'row')} unposted</Badge> : <span className="text-faint">No</span>
              },
            },
            {
              key: 'open',
              header: <span className="sr-only">Action</span>,
              align: 'right',
              priority: 2,
              cell: (c) => (
                <Link
                  to={'/clients/$clientId/reports' as never}
                  params={{ clientId: c.id } as never}
                  search={{ report: 'tb', ...(fy ? { fy } : {}) } as never}
                  className="font-medium text-link hover:underline"
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`Open the Trial Balance of ${c.name}`}
                >
                  Open Trial Balance
                </Link>
              ),
            },
          ]

  return (
    <div className="grid gap-4">
      <PageHeader title={copy.title} description={copy.description} className="mb-0" />
      <ModuleAlerts module={module} />
      <div className="relative w-full max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input aria-label="Search clients" placeholder="Search clients" className="pl-9" value={term} onChange={(e) => setTerm(e.target.value)} />
      </div>
      {overview.error ? (
        <ErrorState error={overview.error} retry={() => void overview.refetch()} />
      ) : (
        <DataTable
          caption={`Clients, ${copy.title}`}
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
      <p className="text-[13px] text-muted-foreground">Choose a client to open it. Alt + C switches client from anywhere.</p>
    </div>
  )
}
