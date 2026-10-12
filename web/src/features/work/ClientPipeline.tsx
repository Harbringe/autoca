// This client's place in the work pipeline: the six stages as one track with the current one marked, what
// to do next as a single row with its button, and who is in charge. The firm-wide board lives on the
// dashboard; here is one client.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import { firmOverview } from '@/api/queries/overview'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { People } from '@/features/clients/ClientTeamScreen'
import { formatDate } from '@/lib/format'
import { nextActionLabel, nextTarget, STAGES, STAGE_HINT, STAGE_LABEL } from '@/lib/overview'
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
  const action = nextActionLabel(c.next_step.code)
  return (
    <div className="grid max-w-[96rem] gap-5">
      <Card className="grid gap-6 rounded-xl p-6 sm:px-8">
        <ol aria-label={`Pipeline stages, step ${at + 1} of ${STAGES.length}`} className="flex gap-3 max-sm:flex-col sm:gap-0">
          {STAGES.map((stage, i) => {
            const done = i < at
            const current = i === at
            return (
              <li key={stage} aria-current={current ? 'step' : undefined} title={STAGE_HINT[stage]} className="relative flex min-w-0 flex-1 items-center gap-2 sm:flex-col sm:gap-2">
                {i < STAGES.length - 1 && (
                  <span aria-hidden className={cn('absolute left-1/2 top-4 hidden h-0.5 w-full sm:block', done ? 'bg-primary' : 'bg-border')} />
                )}
                <span
                  aria-hidden
                  className={cn(
                    'relative z-10 grid size-8 shrink-0 place-items-center rounded-full border-2 bg-card text-[13px] font-semibold text-heading',
                    done && 'border-primary bg-primary text-primary-foreground',
                    current && 'border-accent-edge bg-accent text-accent-foreground',
                    !done && !current && 'border-border',
                  )}
                >
                  {done ? <Check className="size-4" /> : i + 1}
                </span>
                <span className={cn('text-sm font-semibold sm:px-1 sm:text-center', current ? 'text-accent-foreground' : 'text-heading')}>
                  {STAGE_LABEL[stage]}
                  {done && <span className="sr-only"> (done)</span>}
                  {current && <span className="sr-only"> (now)</span>}
                </span>
              </li>
            )
          })}
        </ol>
        <div className="flex flex-wrap items-center justify-between gap-5 border-t pt-6">
          <div className="min-w-0">
            <h2 className="text-sm text-muted-foreground">
              Next step · {c.lead ? `Senior CA ${c.lead.name}` : 'No Senior CA yet'}
              {c.signed_off_through ? ` · signed off to ${formatDate(c.signed_off_through)}` : ''}
            </h2>
            <p className="mt-1.5 text-3xl font-semibold leading-tight text-heading">{c.next_step.label}</p>
            <p className="mt-2 text-sm text-muted-foreground">
              {c.stage === 'needs_ledger'
                ? `Some rows have no ledger yet.${c.pending_approval > 0 ? ` Once they do, ${c.pending_approval} sorted ${c.pending_approval === 1 ? 'entry is' : 'entries are'} ready to post.` : ''}`
                : STAGE_HINT[c.stage]}
            </p>
          </div>
          {action && (
            <Button asChild size="lg">
              <Link to={target.to} params={{ clientId }} search={target.search as never}>
                {action}
              </Link>
            </Button>
          )}
        </div>
      </Card>
      {can('team.view') && <People clientId={clientId} justCreated={false} split />}
    </div>
  )
}
