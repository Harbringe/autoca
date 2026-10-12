// A client's overview: one sentence saying what is waiting, the work as counted cards that each open the
// exact screen where it is done, the year in figures, then the client's profile as one strip. Work comes
// first because that is what a person opening a client is there to do.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Users } from 'lucide-react'
import { invoiceReadings, openItems } from '@/api/queries/bills'
import { gstRegistrations } from '@/api/queries/gst'
import { AddGstinDialog } from '@/features/gst/ClientGst'
import { bankAccounts, clientDetail, reviewSummary } from '@/api/queries/clients'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { OverviewReports } from './OverviewReports'
import { leadSentence } from './overviewLead'

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

  const waiting = {
    unresolved: summary.data?.unresolved ?? 0,
    pending: summary.data?.pending_approval ?? 0,
    invoices: (readings.data ?? []).filter((r) => r.status === 'OPEN').length,
    fixes: fixes.data?.count ?? 0,
    assistant: summary.data?.assistant_waiting ?? 0,
  }
  const loading = summary.isPending && can('transaction.view')

  return (
    <div className="grid max-w-[96rem] gap-6">
      <section aria-labelledby="next-title" className="grid gap-4">
        <h2 id="next-title" className="sr-only">
          What needs you
        </h2>
        {!loading && <p className="max-w-[64ch] text-lg text-heading">{leadSentence(waiting)}</p>}
        <Work
          clientId={clientId}
          loading={loading}
          cards={[
            {
              n: waiting.unresolved,
              label: (n) => (n === 1 ? 'entry to sort into accounts' : 'entries to sort into accounts'),
              action: 'Sort entries',
              tone: 'attention',
              to: '/clients/$clientId/review',
              search: { stage: 'unresolved' },
            },
            {
              n: waiting.pending,
              label: (n) => (n === 1 ? 'sorted entry ready to record' : 'sorted entries ready to record'),
              action: 'Record entries',
              tone: 'ready',
              to: '/clients/$clientId/review',
              search: { stage: 'pending_approval' },
            },
            {
              n: waiting.invoices,
              label: (n) => (n === 1 ? 'invoice waiting to be booked' : 'invoices waiting to be booked'),
              action: 'Book invoices',
              tone: 'plain',
              to: '/clients/$clientId/bills',
            },
            {
              n: waiting.fixes,
              label: (n) => (n === 1 ? 'item that does not tie out' : 'items that do not tie out'),
              action: 'See the items',
              tone: 'plain',
              to: '/clients/$clientId/open-items',
            },
          ]}
        />
      </section>

      <OverviewReports clientId={clientId} />

      <section aria-labelledby="profile-title">
        <h2 id="profile-title" className="sr-only">
          Client profile
        </h2>
        <Card className="flex flex-wrap items-center justify-between gap-x-10 gap-y-5 rounded-xl border-border-strong bg-surface-2 p-6">
          <dl className="flex flex-wrap gap-x-10 gap-y-4">
            <div>
              <dt className="text-sm text-muted-foreground">Senior CA</dt>
              <dd className="mt-1 text-base font-semibold text-heading">{client.data.lead?.name ?? <Badge tone="attention">Not assigned</Badge>}</dd>
            </div>
            <div>
              <dt className="text-sm text-muted-foreground">Year starts</dt>
              <dd className="num mt-1 text-base font-semibold text-heading">{formatDate(client.data.fy_start)}</dd>
            </div>
            <div>
              <dt className="text-sm text-muted-foreground">Bank accounts</dt>
              <dd className="num mt-1 text-base font-semibold text-heading">{accounts.data?.count ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-sm text-muted-foreground">GSTIN</dt>
              <dd className="mt-1 flex flex-wrap items-center gap-x-2 text-base font-semibold text-heading">
                {(registrations.data ?? []).map((r) => (
                  <span key={r.id} className="num">
                    {r.gstin}
                  </span>
                ))}
                {registrations.data?.length === 0 && <Badge tone="attention" className="h-7 rounded-full px-3 text-[13px]">Not added</Badge>}
                {can('journal.approve') && (
                  <Button size="sm" variant="link" className="px-1 text-sm font-semibold text-link" onClick={() => setAddingGstin(true)}>
                    {registrations.data?.length ? 'Add another' : 'Add GSTIN'}
                  </Button>
                )}
              </dd>
            </div>
            {client.data.business_profile && (
              <div className="min-w-0 max-w-xs">
                <dt className="text-sm text-muted-foreground">Business profile</dt>
                <dd className="mt-1 line-clamp-1 text-base font-semibold text-heading" title={client.data.business_profile}>
                  {client.data.business_profile}
                </dd>
              </div>
            )}
          </dl>
          {(can('team.view') || can('client.update')) && (
            <Button asChild variant="outline" size="lg" className="rounded-lg font-semibold text-heading dark:border-border-strong dark:bg-background dark:hover:bg-hover">
              <Link to="/clients/$clientId/team" params={{ clientId }}>
                <Users /> Edit client settings and team
              </Link>
            </Button>
          )}
        </Card>
        {addingGstin && <AddGstinDialog clientId={clientId} onClose={() => setAddingGstin(false)} />}
        {accounts.error && <ErrorState error={accounts.error} retry={() => void accounts.refetch()} />}
      </section>
    </div>
  )
}

interface WorkCard {
  n: number
  label: (n: number) => string
  action: string
  tone: 'attention' | 'ready' | 'plain'
  to: string
  search?: Record<string, string>
}

const NUMBER_TONE = { attention: 'text-accent-foreground', ready: 'text-success', plain: 'text-heading' } as const

/** The client's open work as counted cards, each one button to the exact screen where it is done; or, when there is none, where to go. */
function Work({ clientId, cards, loading }: { clientId: string; cards: WorkCard[]; loading: boolean }) {
  const waiting = cards.filter((c) => c.n > 0)
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
    <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(15rem,1fr))] [&>*]:min-w-0">
      {waiting.map((c, i) => (
        <Card key={c.action} className="flex flex-col gap-4 p-5">
          <div className="flex items-baseline gap-3">
            <span className={cn('num text-5xl font-semibold leading-none', NUMBER_TONE[c.tone])}>{c.n}</span>
            <span className="text-base text-heading">{c.label(c.n)}</span>
          </div>
          <Button asChild variant={i === 0 ? 'primary' : 'secondary'}>
            <Link to={c.to as never} params={{ clientId } as never} search={c.search as never}>
              {c.action}
            </Link>
          </Button>
        </Card>
      ))}
    </div>
  )
}
