import { Link, useRouterState } from '@tanstack/react-router'
import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'
import { CountChip } from './badge'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './dropdown-menu'
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

/**
 * Text tabs that are real links, so each opens in a new tab and shows up in history. 40px tall, a
 * 2px underline in the primary colour on the current one, and a row that scrolls sideways on a phone.
 */
/** Whether this tab is the page the address is on (its path, and the search keys that identify it). */
function isCurrent(tab: TabItem, pathname: string, search: Record<string, unknown>): boolean {
  let path = tab.to
  for (const [key, value] of Object.entries(tab.params ?? {})) path = path.replace(`$${key}`, value)
  if (pathname !== path && !(!tab.exact && pathname.startsWith(`${path}/`))) return false
  return Object.entries(tab.search ?? {}).every(([k, v]) => String(search[k] ?? '') === String(v))
}

export function TabNav({
  label,
  items,
  className,
  trailing,
  maxVisible,
}: {
  label: string
  items: TabItem[]
  className?: string
  trailing?: ReactNode
  /** Past this many tabs the rest go under "More" (about seven is where a row stops being scannable). */
  maxVisible?: number
}) {
  const location = useRouterState({ select: (s) => ({ pathname: s.location.pathname, search: s.location.search as Record<string, unknown> }) })
  const overflowing = maxVisible !== undefined && items.length > maxVisible + 1
  const shown = overflowing ? items.slice(0, maxVisible) : items
  const more = overflowing ? items.slice(maxVisible) : []
  const moreActive = more.some((t) => isCurrent(t, location.pathname, location.search))
  return (
    <div className={cn('no-print flex items-end justify-between gap-3 border-b', className)}>
      <nav aria-label={label} className="-mb-px flex min-w-0 gap-1 overflow-x-auto [scrollbar-width:none]">
        {shown.map((tab) => (
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
        {more.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger
              className={cn(
                'flex h-10 items-center gap-1 whitespace-nowrap border-b-2 px-3 text-sm font-medium',
                moreActive ? 'border-primary text-heading' : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              {moreActive ? (more.find((t) => isCurrent(t, location.pathname, location.search))?.label ?? 'More') : 'More'}
              <ChevronDown className="size-4" aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {more.map((tab) => (
                <DropdownMenuItem key={`${tab.to}${JSON.stringify(tab.search ?? '')}`} asChild>
                  <Link
                    to={tab.to as never}
                    params={tab.params as never}
                    search={(tab.search ? (prev: Record<string, unknown>) => ({ ...prev, ...tab.search }) : undefined) as never}
                  >
                    {tab.label}
                    {tab.count ? <CountChip>{tab.count}</CountChip> : null}
                  </Link>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </nav>
      {trailing}
    </div>
  )
}
