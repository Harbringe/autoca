import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Plus, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { booksStatus, clientsList, reviewSummary, statements } from '@/api/queries/clients'
import { unsignedThrough } from '@/features/books/state'
import { formatDate, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { useSession } from '@/session/session'
import { NewClientDialog } from './NewClientDialog'

const PAGE_SIZE = 50

export function ClientsScreen() {
  const { can } = useSession()
  const [search, setSearch] = useState('')
  const [term, setTerm] = useState('')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)

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

  const total = clients.data?.count ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <PageHeader
        title="Clients"
        description={clients.data ? plural(total, 'client') : undefined}
        actions={
          canCreate && (
            <Button onClick={() => setCreating(true)}>
              <Plus /> New client
            </Button>
          )
        }
      />

      <div className="relative mb-4 max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          aria-label="Search clients"
          placeholder="Search by name"
          className="pl-9"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {clients.isPending ? (
        <Spinner label="Loading clients…" />
      ) : clients.error ? (
        <ErrorState error={clients.error} retry={() => void clients.refetch()} />
      ) : clients.data.results.length === 0 ? (
        term ? (
          <EmptyState title="No client matches that name">Check the spelling, or search for part of the name.</EmptyState>
        ) : canCreate ? (
          <EmptyState
            title="No clients yet"
            action={
              <Button onClick={() => setCreating(true)}>
                <Plus /> Add your first client
              </Button>
            }
          >
            A client is one set of books: its own chart of accounts, statements and financial year.
          </EmptyState>
        ) : (
          <EmptyState title="No clients assigned to you">
            You will see a client here once your senior CA assigns you to it.
          </EmptyState>
        )
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-muted/50 text-[13px] text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Client</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Financial year starts</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Senior CA in charge</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Next step</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {clients.data.results.map((client) => (
                <tr key={client.id} className="h-(--row-h) hover:bg-hover">
                  <td className="px-4 font-medium">
                    <Link to="/clients/$clientId" params={{ clientId: client.id }} className="hover:underline">
                      {client.name}
                    </Link>
                  </td>
                  <td className="num px-4 text-muted-foreground">
                    {formatDate(client.fy_start)}
                  </td>
                  <td className="px-4 text-muted-foreground">
                    {client.lead?.name ?? <span className="text-warning">Not assigned</span>}
                  </td>
                  <td className="px-4">
                    <NextStep clientId={client.id} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 && (
            <div className="flex items-center justify-between border-t px-4 py-2.5 text-[13px] text-muted-foreground">
              <span>
                Page {page} of {pages}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      <NewClientDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}

/** What this client's books need next, in a few words, linking straight to where it is done. */
function NextStep({ clientId }: { clientId: string }) {
  const stmts = useQuery(statements(clientId))
  const books = useQuery(booksStatus(clientId))
  const summary = useQuery(reviewSummary(clientId))
  if (stmts.isPending || summary.isPending || books.isPending) return <span className="text-muted-foreground">…</span>
  if (!stmts.data?.count)
    return (
      <Link to="/clients/$clientId/statements" params={{ clientId }} className="text-info hover:underline">
        Upload a bank statement
      </Link>
    )
  const s = summary.data
  if (s?.unresolved)
    return (
      <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'unresolved' }} className="text-warning hover:underline">
        {plural(s.unresolved, 'row')} {s.unresolved === 1 ? 'needs' : 'need'} a ledger
      </Link>
    )
  if (s?.pending_approval)
    return (
      <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'pending_approval' }} className="text-info hover:underline">
        {plural(s.pending_approval, 'row')} ready to post
      </Link>
    )
  const b = books.data
  if (b?.review_pending)
    return (
      <Link to="/clients/$clientId/books" params={{ clientId }} className="text-info hover:underline">
        Awaiting sign-off
      </Link>
    )
  const latest = stmts.data?.results.reduce<string | null>((max, s) => (!max || s.period_end > max ? s.period_end : max), null) ?? null
  if (b && unsignedThrough(b, latest))
    return (
      <Link to="/clients/$clientId/books" params={{ clientId }} className="text-warning hover:underline">
        Send for review{b.signed_off_through ? ` (after ${formatDate(b.signed_off_through)})` : ''}
      </Link>
    )
  return <span className="text-success">Signed off to date</span>
}
