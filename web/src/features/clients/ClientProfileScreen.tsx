import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Building2, Users } from 'lucide-react'
import { invoiceReadings, openItems } from '@/api/queries/bills'
import { gstRegistrations } from '@/api/queries/gst'
import { AddGstinDialog } from '@/features/gst/ClientGst'
import { bankAccounts, clientDetail, reviewSummary } from '@/api/queries/clients'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'
import { useSession } from '@/session/session'

export function ClientProfileScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const accounts = useQuery({ ...bankAccounts(clientId), enabled: can('transaction.view') })
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  const fixes = useQuery({ ...openItems(clientId), enabled: can('journal.view') })
  const readings = useQuery({ ...invoiceReadings(clientId), enabled: can('journal.view') })
  const registrations = useQuery({ ...gstRegistrations(clientId), enabled: can('journal.view') })
  const [addingGstin, setAddingGstin] = useState(false)

  if (client.isPending) return <Spinner label="Loading client details…" />
  if (client.error) return <ErrorState error={client.error} retry={() => void client.refetch()} />

  return (
    <div className="grid max-w-6xl gap-5">
      <section aria-labelledby="profile-title" className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2"><Building2 className="size-4 text-muted-foreground" /><h2 id="profile-title" className="text-[15px] font-semibold text-heading">Client profile</h2></div>
          {(can('team.view') || can('client.update')) && <Button asChild variant="secondary" size="sm"><Link to="/clients/$clientId/team" params={{ clientId }}><Users /> Edit client settings and team</Link></Button>}
        </div>
        <Card className="p-5">
          <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-5">
            <div><dt className="text-xs text-muted-foreground">Senior CA in charge</dt><dd className="mt-1 text-sm font-medium text-heading">{client.data.lead?.name ?? <Badge tone="attention">Not assigned</Badge>}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Financial year starts</dt><dd className="num mt-1 text-sm font-medium text-heading">{formatDate(client.data.fy_start)}</dd></div>
            <div>
              <dt className="text-xs text-muted-foreground">GSTIN</dt>
              <dd className="mt-1 grid gap-1 text-sm font-medium text-heading">
                {(registrations.data ?? []).map((r) => <span key={r.id} className="num">{r.gstin}</span>)}
                {registrations.data?.length === 0 && <Badge tone="attention">Not added</Badge>}
                {can('journal.approve') && <Button size="sm" variant="ghost" className="justify-self-start px-0" onClick={() => setAddingGstin(true)}>{registrations.data?.length ? 'Add another' : 'Add GSTIN'}</Button>}
              </dd>
            </div>
            <div><dt className="text-xs text-muted-foreground">Bank accounts</dt><dd className="num mt-1 text-sm font-medium text-heading">{accounts.data?.count ?? '—'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Business profile</dt><dd className="mt-1 line-clamp-2 text-sm font-medium text-heading">{client.data.business_profile || 'Not added'}</dd></div>
          </dl>
        </Card>
        {addingGstin && <AddGstinDialog clientId={clientId} onClose={() => setAddingGstin(false)} />}
        {accounts.error && <ErrorState error={accounts.error} retry={() => void accounts.refetch()} />}
      </section>

      <section aria-labelledby="next-title" className="grid gap-3">
        <h2 id="next-title" className="text-[15px] font-semibold text-heading">What needs you</h2>
        <Next
          clientId={clientId}
          loading={summary.isPending && can('transaction.view')}
          rows={[
            { n: summary.data?.unresolved ?? 0, text: (n) => `${plural(n, 'entry', 'entries')} to sort into accounts`, to: '/clients/$clientId/review', search: { stage: 'unresolved' } },
            { n: summary.data?.pending_approval ?? 0, text: (n) => `${plural(n, 'sorted entry', 'sorted entries')} ready to record`, to: '/clients/$clientId/review', search: { stage: 'pending_approval' } },
            { n: (readings.data ?? []).filter((r) => r.status === 'OPEN').length, text: (n) => `${plural(n, 'invoice')} waiting to be booked`, to: '/clients/$clientId/bills' },
            { n: fixes.data?.count ?? 0, text: (n) => `${plural(n, 'item')} that do not tie out`, to: '/clients/$clientId/open-items' },
          ]}
        />
      </section>
    </div>
  )
}

interface NextRow {
  n: number
  text: (n: number) => string
  to: string
  search?: Record<string, string>
}

/** The client's open work as a short list, each line the exact screen where it is done; or, when there is none, where to go. */
function Next({ clientId, rows, loading }: { clientId: string; rows: NextRow[]; loading: boolean }) {
  const waiting = rows.filter((r) => r.n > 0)
  if (loading) return <Spinner label="Looking at what is waiting…" />
  if (waiting.length === 0) {
    return (
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="text-sm text-muted-foreground">Nothing is waiting on this client. Upload the next bank statement, or look at the reports.</p>
        <div className="flex gap-2">
          <Button asChild size="sm" variant="secondary">
            <Link to="/clients/$clientId/statements" params={{ clientId }}>Bank statements</Link>
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link to="/clients/$clientId/reports" params={{ clientId }} search={{ report: 'tb' }}>Reports</Link>
          </Button>
        </div>
      </Card>
    )
  }
  return (
    <Card className="divide-y p-0">
      {waiting.map((row) => (
        <Link
          key={row.text(row.n)}
          to={row.to as never}
          params={{ clientId } as never}
          search={row.search as never}
          className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-hover"
        >
          <span>{row.text(row.n)}</span>
          <span className="font-medium text-link">Open</span>
        </Link>
      ))}
    </Card>
  )
}
