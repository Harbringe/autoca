import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
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
  /** Extra keys in the URL that identify the tab, e.g. ?report=tb. */
  search?: Record<string, unknown>
}

/**
 * Text tabs that are real links, so each opens in a new tab and shows up in history. 40px tall, a
 * 2px underline in the primary colour on the current one, and a row that scrolls sideways on a phone.
 */
export function TabNav({ label, items, className, trailing }: { label: string; items: TabItem[]; className?: string; trailing?: ReactNode }) {
  return (
    <div className={cn('no-print flex items-end justify-between gap-3 border-b', className)}>
      <nav aria-label={label} className="-mb-px flex min-w-0 gap-1 overflow-x-auto [scrollbar-width:none]">
        {items.map((tab) => (
          <Link
            key={`${tab.to}${JSON.stringify(tab.search ?? '')}`}
            to={tab.to as never}
            params={tab.params as never}
            search={tab.search as never}
            activeOptions={{ exact: !!tab.exact, includeSearch: false }}
            className="flex h-10 items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent px-3 text-sm font-medium text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-heading"
          >
            {tab.label}
            {tab.count ? <CountChip>{tab.count}</CountChip> : null}
          </Link>
        ))}
      </nav>
      {trailing}
    </div>
  )
}
