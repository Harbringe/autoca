// The review screen's tabs. Three are queues of rows still waiting; the fourth, Posted, is the
// other side of the line: what has already become an entry in the books.

import { useQuery } from '@tanstack/react-query'
import { Link, useSearch } from '@tanstack/react-router'
import { useLayoutEffect, useRef, useState } from 'react'
import { journal, type ReviewTab } from '@/api/queries/books'
import { reviewSummary } from '@/api/queries/clients'
import { cn } from '@/lib/utils'
import { useReviewScope } from './useReviewScope'
import { useSession } from '@/session/session'

export const STAGES: { stage: ReviewTab; label: string; hint: string }[] = [
  { stage: 'unresolved', label: 'Needs a ledger', hint: 'No ledger yet. Decide where each one goes.' },
  { stage: 'pending_approval', label: 'Ready to post', hint: 'Placed in a ledger, not yet in the books. Check and post.' },
  { stage: 'all', label: 'All waiting', hint: 'Everything not yet posted.' },
  { stage: 'posted', label: 'Posted', hint: 'Entries already in the books, in every financial year.' },
]

type Box = { x: number; y: number; w: number; h: number }
// Each tab's page draws its own copy of the nav, so the lit shape is remembered here and the next copy starts from where it was.
let lastBox: Box | null = null

export function StageNav({ clientId, active }: { clientId: string; active: ReviewTab }) {
  const { can } = useSession()
  const summary = useQuery(reviewSummary(clientId))
  const canSeePosted = can('journal.view')
  const posted = useQuery({ ...journal(clientId), enabled: canSeePosted })
  const tabs = STAGES.filter((s) => s.stage !== 'posted' || canSeePosted)
  // With statements chosen, every number on the tabs is theirs, not the client's.
  const asked = useSearch({ strict: false }) as { statement?: string }
  const { counts: scoped } = useReviewScope(clientId, asked.statement)

  // The lit tab is one shape that glides to the tab you chose, rather than each tab switching its own background.
  const nav = useRef<HTMLElement>(null)
  const links = useRef<Record<string, HTMLAnchorElement | null>>({})
  const [box, setBox] = useState<Box | null>(lastBox)
  const arrived = useRef(false)
  const measure = () => {
    const el = links.current[active]
    if (el && el.offsetWidth > 0) {
      const next = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }
      lastBox = next
      // Only when it moved: setting an equal copy would draw again, measure again, and never stop.
      setBox((was) => (was && was.x === next.x && was.y === next.y && was.w === next.w && was.h === next.h ? was : next))
    }
  }
  useLayoutEffect(() => {
    // A copy that has just appeared draws once where the last one was, then moves, so the change is seen.
    if (!arrived.current && lastBox) {
      arrived.current = true
      const frame = requestAnimationFrame(measure)
      return () => cancelAnimationFrame(frame)
    }
    arrived.current = true
    measure()
  })
  useLayoutEffect(() => {
    if (!nav.current || typeof ResizeObserver === 'undefined') return
    const watcher = new ResizeObserver(measure)
    watcher.observe(nav.current)
    return () => watcher.disconnect()
  })
  const glides = !!box && box.w > 0

  return (
    <nav ref={nav} aria-label="Review stage" className="relative flex flex-wrap gap-1 rounded-lg bg-muted p-1">
      {glides && (
        <span
          aria-hidden
          className="absolute left-0 top-0 rounded-md bg-card shadow-xs transition-[transform,width,height] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]"
          style={{ width: box.w, height: box.h, transform: `translate(${box.x}px, ${box.y}px)` }}
        />
      )}
      {tabs.map((s) => {
        const count = scoped
          ? scoped[s.stage === 'posted' ? 'posted' : s.stage]
          : s.stage === 'unresolved'
            ? summary.data?.unresolved
            : s.stage === 'pending_approval'
              ? summary.data?.pending_approval
              : s.stage === 'posted'
                ? posted.data?.length
                : summary.data?.total
        return (
          <Link
            key={s.stage}
            ref={(el) => {
              links.current[s.stage] = el
            }}
            to="/clients/$clientId/review"
            params={{ clientId }}
            search={((prev: Record<string, unknown>) => ({ ...prev, stage: s.stage })) as never}
            className={cn('relative z-10 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors duration-200', active === s.stage && (glides ? 'text-foreground' : 'bg-card text-foreground shadow-xs'))}
          >
            {s.label} <span className="num ml-1 text-xs">{count ?? '…'}</span>
          </Link>
        )
      })}
    </nav>
  )
}
