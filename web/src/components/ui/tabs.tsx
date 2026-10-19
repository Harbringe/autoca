import { Link, useRouterState } from '@tanstack/react-router'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { CountChip } from './badge'
import { cn } from '@/lib/utils'

export interface TabItem {
  /** A route path, with $params filled from `params`. */
  to: string
  params?: Record<string, string>
  label: string
  count?: number
  /** Match only this exact path (the first tab of a module). */
  exact?: boolean
  /**
   * Extra keys in the URL that identify the tab, e.g. ?report=tb. They are merged over the current
   * search, so ?fy= survives, and the tab is current only when they all match.
   */
  search?: Record<string, unknown>
}

/** How far one press of an arrow moves the row. */
const SCROLL_STEP = 240

/**
 * Text tabs that are real links, so each opens in a new tab and shows up in history. 40px tall, a
 * 2px underline in the primary colour on the current one. A row wider than its space scrolls sideways
 * (by touch, wheel or the arrow shown on each side that has more tabs beyond it).
 */
export function TabNav({ label, items, className, trailing }: { label: string; items: TabItem[]; className?: string; trailing?: ReactNode }) {
  const location = useRouterState({ select: (s) => ({ pathname: s.location.pathname, search: s.location.search as Record<string, unknown> }) })
  const row = useRef<HTMLElement>(null)
  const [beyond, setBeyond] = useState({ left: false, right: false })
  const measure = useCallback(() => {
    const el = row.current
    if (!el) return
    const left = el.scrollLeft > 1
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1
    setBeyond((b) => (b.left === left && b.right === right ? b : { left, right }))
  }, [])
  useEffect(() => {
    const el = row.current
    if (!el) return
    measure()
    el.addEventListener('scroll', measure, { passive: true })
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(el)
    return () => {
      el.removeEventListener('scroll', measure)
      observer?.disconnect()
    }
  }, [measure, items.length])
  // The tab you are on is kept in view, so opening a screen far along the row does not hide where you are.
  useEffect(() => {
    row.current?.querySelector('[data-status="active"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [location.pathname, location.search])
  const scrollBy = (direction: -1 | 1) => row.current?.scrollBy?.({ left: direction * SCROLL_STEP, behavior: 'smooth' })
  const arrow = 'flex h-10 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-hover hover:text-heading'
  return (
    <div className={cn('no-print flex select-none items-end justify-between gap-3 border-b', className)}>
      <div className="flex min-w-0 items-end gap-1">
        {beyond.left && (
          <button type="button" className={arrow} aria-label={`Scroll ${label} left`} onClick={() => scrollBy(-1)}>
            <ChevronLeft className="size-4" aria-hidden />
          </button>
        )}
        <nav ref={row} aria-label={label} className="-mb-px flex min-w-0 gap-1 overflow-x-auto [scrollbar-width:none]">
          {items.map((tab) => (
            <Link
              key={`${tab.to}${JSON.stringify(tab.search ?? '')}`}
              to={tab.to as never}
              params={tab.params as never}
              search={(tab.search ? (prev: Record<string, unknown>) => ({ ...prev, ...tab.search }) : undefined) as never}
              activeOptions={{ exact: !!tab.exact, includeSearch: !!tab.search }}
              className="flex h-10 items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent px-3 text-sm font-medium text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-heading"
            >
              {tab.label}
              {tab.count ? <CountChip>{tab.count}</CountChip> : null}
            </Link>
          ))}
        </nav>
        {beyond.right && (
          <button type="button" className={arrow} aria-label={`Scroll ${label} right`} onClick={() => scrollBy(1)}>
            <ChevronRight className="size-4" aria-hidden />
          </button>
        )}
      </div>
      {trailing}
    </div>
  )
}
