// Ready rows seen as groups of alike ones: the same payee, the same ledger, the same direction. A year's statement is hundreds of rows that
// are really a few dozen decisions, so each group is one line with what it came to and one button, instead of a page of near-identical rows.

import { CheckCheck } from 'lucide-react'
import { PagedList } from '@/components/ca/Pager'
import { Button } from '@/components/ui/button'
import { formatPaise, plural } from '@/lib/format'
import type { SimilarGroup } from './similarGroups'

function How({ g }: { g: SimilarGroup }) {
  const parts = [g.byRule ? `${g.byRule} by a rule` : '', g.byModel ? `${g.byModel} by the assistant` : '', g.byPerson ? `${g.byPerson} by a person` : ''].filter(Boolean)
  return <>{parts.join(' · ')}</>
}

export function SimilarGroupList({
  groups,
  canPost,
  onPost,
  onShow,
}: {
  groups: SimilarGroup[]
  canPost: boolean
  onPost: (group: SimilarGroup) => void
  onShow: (group: SimilarGroup) => void
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border-strong bg-surface-2">
      <p className="border-b border-border-strong px-4 py-2.5 text-[13px] text-muted-foreground">
        {plural(groups.length, 'group')} of alike rows, the largest first. Each group is one payee in one ledger. Post a whole group when its ledger is right; open it to see the rows.
      </p>
      <PagedList rows={groups} resetKey={`${groups.length}`} label="Groups of alike rows" section="review">
        {(shown) => (
          <ul aria-label="Groups of alike rows" className="divide-y divide-border-strong">
            {shown.map((g) => (
              <li key={g.key} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
                <div className="min-w-0 flex-1 basis-64">
                  <div className="flex flex-wrap items-center gap-2">
                    <b className="min-w-0 truncate font-medium text-heading">{g.label}</b>
                    <span className="num rounded-full border px-2 text-xs font-semibold">{g.rows.length}</span>
                    <span className="text-xs text-muted-foreground">{g.debit ? 'paid out' : 'received'}</span>
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted-foreground">
                    in <b className="font-medium text-foreground">{g.ledgerName}</b> · <How g={g} />
                  </div>
                </div>
                <span className="num shrink-0 text-right text-sm font-semibold">{formatPaise(g.totalPaise)}</span>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" variant="outline" onClick={() => onShow(g)}>
                    Open rows
                  </Button>
                  {canPost && (
                    <Button size="sm" onClick={() => onPost(g)} aria-label={`Post all ${g.rows.length} rows like ${g.label}`}>
                      <CheckCheck /> Post all {g.rows.length}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </PagedList>
    </div>
  )
}
