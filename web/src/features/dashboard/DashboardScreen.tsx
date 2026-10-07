// The front door. One screen, three layouts: the signed-in role decides which, so each person starts on
// the answer to their own question (the owner: is the firm on track; a Senior CA: what is waiting on me;
// staff: what do I do next). The portfolio the server sends is already scoped by role, so every layout
// reads the same data. The live work queue, once the second tab, is a section opened on purpose.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronDown, FileUp } from 'lucide-react'
import { useId, useState } from 'react'
import { portfolio } from '@/api/queries/dashboard'
import type { Portfolio } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { clientHealth, layoutFor, type DashboardLayout } from '@/lib/dashboard'
import { formatDateLong, plural } from '@/lib/format'
import { isoOf } from '@/lib/period'
import { usePageTitle } from '@/lib/title'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { OwnerDashboard, SeniorDashboard, StaffDashboard } from './layouts'
import { LiveQueue } from './LiveQueue'

/** The reader's question, answered in one plain sentence from what the portfolio says. */
export function questionLine(layout: DashboardLayout, data: Portfolio | undefined): string {
  if (!data) return { owner: 'Is my firm on track?', senior: 'What do I need to approve or seal, and which clients are at risk?', staff: 'What do I do next?' }[layout]
  const clients = data.clients
  const health = clients.map(clientHealth)
  const late = health.filter((h) => h.health === 'overdue').length
  const risk = health.filter((h) => h.health !== 'on_track').length
  if (layout === 'owner') {
    const on = health.length - risk
    return `Is my firm on track? ${on} of ${plural(health.length, 'client')} ${on === 1 ? 'is' : 'are'} on track${late ? `; ${late} ${late === 1 ? 'is' : 'are'} late.` : '.'}`
  }
  if (layout === 'senior') {
    const waiting = clients.filter((c) => c.review_pending).length
    return `What is waiting on me? ${plural(waiting, 'book')} to approve, ${plural(risk, 'client')} at risk.`
  }
  const work = data.totals.unresolved + data.totals.pending_approval
  return work ? `What do I do next? ${plural(work, 'entry', 'entries')} on my clients ${work === 1 ? 'is' : 'are'} waiting.` : 'What do I do next? Nothing is waiting on my clients.'
}

export function DashboardScreen() {
  usePageTitle('Dashboard')
  const { me, can } = useSession()
  const layout = layoutFor(me?.role)
  const query = useQuery(portfolio())
  const today = new Date()
  const data = query.data
  const state = query.isLoading ? 'loading' : 'ready'

  return (
    <div className="grid gap-4 [&>*]:min-w-0">
      <PageHeader
        title="Dashboard"
        className="mb-1"
        description={
          <>
            {questionLine(layout, data)} <span className="whitespace-nowrap text-faint">· {me?.firm?.name ?? 'Your firm'}, {formatDateLong(isoOf(today))}</span>
          </>
        }
      />
      {query.error ? (
        <ErrorState error={query.error} retry={() => void query.refetch()} />
      ) : data && data.clients.length === 0 ? (
        <EmptyState
          title="No clients yet"
          action={can('client.create') && <Button asChild><Link to="/clients"><FileUp /> Add your first client</Link></Button>}
        >
          {layout === 'staff' ? 'You are not on any client yet. Ask your Senior CA to add you to one.' : 'A client is one set of books. Add one, then upload its bank statement.'}
        </EmptyState>
      ) : layout === 'owner' ? (
        <OwnerDashboard data={data} state={state} today={today} />
      ) : layout === 'senior' ? (
        <SeniorDashboard data={data} state={state} today={today} />
      ) : (
        <StaffDashboard data={data} state={state} today={today} />
      )}
      {layout !== 'staff' && !query.error && <LiveQueueSection />}
    </div>
  )
}

function LiveQueueSection() {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <section aria-labelledby={`${id}-t`} className="no-print mt-2 border-t pt-4">
      <h2 id={`${id}-t`} className="text-[15px] font-semibold text-heading">
        <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} className="-ml-2 inline-flex min-h-11 items-center gap-2 rounded-md px-2 hover:bg-hover sm:min-h-9">
          <ChevronDown className={cn('size-4 text-muted-foreground', !open && '-rotate-90')} aria-hidden />
          Live work queue
          <span className="text-[13px] font-normal text-muted-foreground">{open ? 'Updates every 15 seconds' : 'Open to see what is waiting right now'}</span>
        </button>
      </h2>
      <div id={id} hidden={!open} className="mt-3">
        {open && <LiveQueue />}
      </div>
    </section>
  )
}
