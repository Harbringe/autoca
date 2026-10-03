// The review screen's tabs. Three are queues of rows still waiting; the fourth, Posted, is the
// other side of the line: what has already become an entry in the books.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { journal, type ReviewTab } from '@/api/queries/books'
import { reviewSummary } from '@/api/queries/clients'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export const STAGES: { stage: ReviewTab; label: string; hint: string }[] = [
  { stage: 'unresolved', label: 'Needs a ledger', hint: 'No ledger yet. Decide where each one goes.' },
  { stage: 'pending_approval', label: 'Ready to post', hint: 'Placed in a ledger, not yet in the books. Check and post.' },
  { stage: 'all', label: 'All waiting', hint: 'Everything not yet posted.' },
  { stage: 'posted', label: 'Posted', hint: 'Entries already in the books, in every financial year.' },
]

export function StageNav({ clientId, active }: { clientId: string; active: ReviewTab }) {
  const { can } = useSession()
  const summary = useQuery(reviewSummary(clientId))
  const canSeePosted = can('journal.view')
  const posted = useQuery({ ...journal(clientId), enabled: canSeePosted })
  const tabs = STAGES.filter((s) => s.stage !== 'posted' || canSeePosted)

  return (
    <nav aria-label="Review stage" className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
      {tabs.map((s) => {
        const count =
          s.stage === 'unresolved'
            ? summary.data?.unresolved
            : s.stage === 'pending_approval'
              ? summary.data?.pending_approval
              : s.stage === 'posted'
                ? posted.data?.length
                : summary.data?.total
        return (
          <Link
            key={s.stage}
            to="/clients/$clientId/review"
            params={{ clientId }}
            search={{ stage: s.stage }}
            className={cn('rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground', active === s.stage && 'bg-card text-foreground shadow-xs')}
          >
            {s.label} <span className="num ml-1 text-xs">{count ?? '…'}</span>
          </Link>
        )
      })}
    </nav>
  )
}
