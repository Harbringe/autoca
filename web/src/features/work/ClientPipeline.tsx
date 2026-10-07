// This client's place in the work pipeline: the stages in order with the current one marked, what
// to do next, and who is in charge. The firm-wide board lives on the dashboard; here is one client.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import { firmOverview } from '@/api/queries/overview'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { People } from '@/features/clients/ClientTeamScreen'
import { formatDate } from '@/lib/format'
import { nextTarget, STAGES, STAGE_HINT, STAGE_LABEL, STAGE_TONE } from '@/lib/overview'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export function ClientPipeline({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const overview = useQuery(firmOverview())
  if (overview.error) return <ErrorState error={overview.error} retry={() => void overview.refetch()} />
  if (overview.isLoading || !overview.data) return <Spinner label="Loading the pipeline…" />
  const c = overview.data.clients.find((x) => x.id === clientId)
  if (!c) return <EmptyState title="Not in the pipeline">This client’s stage is not available.</EmptyState>
  const at = STAGES.indexOf(c.stage)
  const target = nextTarget(c.next_step.code)
  return (
    <div className="grid gap-4">
      <ol aria-label="Pipeline stages" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        {STAGES.map((stage, i) => {
          const current = i === at
          return (
            <li key={stage} aria-current={current ? 'step' : undefined} className={cn('rounded-lg border p-3', current ? 'border-primary bg-card' : 'bg-surface-2')}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold text-heading">{STAGE_LABEL[stage]}</span>
                {i < at ? <Check className="size-4 text-muted-foreground" aria-label="Done" /> : current ? <Badge tone={STAGE_TONE[stage]}>Now</Badge> : null}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{STAGE_HINT[stage]}</p>
            </li>
          )
        })}
      </ol>
      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-semibold text-heading">Next step</h2>
        <Link to={target.to} params={{ clientId }} search={target.search as never} className="mt-1 inline-block text-sm font-medium text-link hover:underline">
          {c.next_step.label}
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">
          {c.lead ? c.lead.name : 'No Senior CA yet'}
          {c.signed_off_through ? ` · signed off to ${formatDate(c.signed_off_through)}` : ''}
        </p>
      </section>
      {can('team.view') && (
        <section className="rounded-lg border bg-card p-4">
          <h2 className="mb-2 text-sm font-semibold text-heading">Who is in charge</h2>
          <People clientId={clientId} justCreated={false} />
        </section>
      )}
    </div>
  )
}
