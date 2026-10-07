// What takes the place of the rail and the panel below 1024px: a full-width client button in the top
// bar (it opens the same switcher), and a strip of the five screens used most under it.

import { Link, useRouterState } from '@tanstack/react-router'
import { ChevronsUpDown } from 'lucide-react'
import { clientScreenPath, stripFor, stripIsActive } from '@/lib/clientNav'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { useClientHeader } from './clientHeader'
import { ClientSwitcher } from './ClientSwitcher'
import { useReviewCount } from './ClientPanel'

/** The client's name, with the year and state beneath, as one 44px button that opens the switcher. */
export function PhoneClientButton({ clientId }: { clientId: string }) {
  const { name, line } = useClientHeader(clientId)
  return (
    <ClientSwitcher currentId={clientId} align="center">
      <button
        type="button"
        aria-label={`${name ?? 'Client'}${line ? `, ${line}` : ''}. Switch client`}
        className="flex h-11 min-w-0 flex-1 items-center gap-2 rounded-lg border border-input bg-card px-3 text-left"
      >
        <span className="min-w-0 flex-1 leading-4">
          <span className="block truncate text-sm font-semibold text-heading">{name ?? '…'}</span>
          <span className="block truncate text-xs text-muted-foreground">{line}</span>
        </span>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </button>
    </ClientSwitcher>
  )
}

/** Overview, Bank, Documents, Books, GST, Reports: 44px targets in a row that scrolls sideways inside itself. */
export function ClientStrip({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const reviewCount = useReviewCount(clientId)
  return (
    <nav aria-label="Client screens" className="no-print sticky top-14 z-20 border-b bg-background">
      <ul className="flex gap-2 overflow-x-auto overscroll-x-contain px-3 py-2 [scrollbar-width:none]">
        {stripFor(can).map((item) => {
          const isActive = stripIsActive(item, path)
          return (
            <li key={item.screen || 'overview'} className="shrink-0">
              <Link
                to={clientScreenPath(clientId, item.screen) as never}
                activeOptions={{ exact: true, includeSearch: false }}
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'flex h-11 items-center gap-1.5 rounded-full border px-4 text-sm font-medium',
                  isActive ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-foreground hover:bg-hover',
                )}
              >
                {item.label}
                {item.screen === 'statements' && reviewCount ? (
                  <span className="num rounded-sm bg-sidebar-chip px-1.5 text-xs font-medium text-sidebar-chip-foreground">
                    {reviewCount}
                    <span className="sr-only"> rows waiting</span>
                  </span>
                ) : null}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
