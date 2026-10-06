// The slim rail: always there on a desktop, 72px wide, the firm's few places with their names under
// the icons, then the clients opened lately as small discs, then the person. It looks the same whichever
// page you are on; only the highlighted place changes.

import { Link, useRouterState } from '@tanstack/react-router'
import { Activity, Bell, Columns3, LayoutDashboard, Settings, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { useAlertCount } from '@/features/alerts/AlertBell'
import { clientIdOf } from '@/lib/modules'
import { useClientMemory } from '@/lib/recentClients'
import { railActive, railHref, railItems, type RailItem } from '@/lib/sidebarNav'
import { initialsOf } from '@/lib/useDebounced'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { useClientNames } from './clientHeader'
import { UserMenu } from './UserMenu'

export const RAIL_ICONS: Record<RailItem['id'], ReactNode> = {
  dashboard: <LayoutDashboard />,
  clients: <Users />,
  pipeline: <Columns3 />,
  alerts: <Bell />,
  staff: <Activity />,
  settings: <Settings />,
}

const RECENT_SHOWN = 4

export function Rail({ onShortcuts }: { onShortcuts: () => void }) {
  const { can } = useSession()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const clientId = clientIdOf(path)
  const items = railItems(can)
  const active = railActive(path)
  // The firm's count belongs to the firm's pages; inside a client the bell speaks for that client.
  const alertCount = useAlertCount(!clientId)

  return (
    <div className="flex h-full w-[72px] flex-col items-center overflow-y-auto overscroll-contain bg-sidebar py-3 text-sidebar-foreground [scrollbar-width:none]">
      <Link
        to={(items[0] ? railHref(items[0], can) : '/clients') as never}
        aria-label="AutoCA home"
        className="mb-2 grid size-9 shrink-0 place-items-center rounded-lg bg-brand text-[13px] font-bold tracking-tight text-white"
      >
        CA
      </Link>
      <nav aria-label="Main" className="flex w-full flex-col items-center gap-0.5 px-1.5">
        {items.map((item) => {
          const isActive = active === item.id
          const count = item.id === 'alerts' && alertCount ? alertCount : 0
          return (
            <Link
              key={item.id}
              to={railHref(item, can) as never}
              activeOptions={{ exact: true, includeSearch: false }}
              aria-current={isActive ? 'page' : undefined}
              className={cn(
                'relative flex w-full flex-col items-center gap-1 rounded-lg pb-1.5 pt-2 text-[11px] font-medium leading-3 text-sidebar-foreground hover:bg-white/5 hover:text-white [&_svg]:size-5',
                isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-2 before:-left-1.5 before:w-[3px] before:rounded-full before:bg-sidebar-bar',
              )}
            >
              {RAIL_ICONS[item.id]}
              {item.label}
              {count > 0 && (
                <span className="num absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-sidebar-chip px-1 text-[10px] font-semibold leading-4 text-sidebar-chip-foreground">
                  {count > 99 ? '99+' : count}
                  <span className="sr-only"> need attention</span>
                </span>
              )}
            </Link>
          )
        })}
      </nav>
      <RecentClients currentId={clientId} />
      <div className="flex-1" />
      <UserMenu variant="rail" onShortcuts={onShortcuts} />
    </div>
  )
}

function RecentClients({ currentId }: { currentId?: string }) {
  const { recent } = useClientMemory()
  const named = useClientNames(recent.slice(0, RECENT_SHOWN + 1)).slice(0, RECENT_SHOWN)
  if (named.length === 0) return null
  return (
    <section aria-label="Recent clients" className="mt-3 flex w-full flex-col items-center gap-2 border-t border-white/10 px-1.5 pt-3">
      <h2 className="text-[11px] font-medium uppercase tracking-[0.06em] text-sidebar-muted">Recent</h2>
      {named.map((c) => {
        const current = c.id === currentId
        return (
          <Link
            key={c.id}
            to="/clients/$clientId"
            params={{ clientId: c.id }}
            activeOptions={{ exact: true, includeSearch: false }}
            aria-label={c.name}
            aria-current={current ? 'page' : undefined}
            title={c.name}
            className={cn(
              'grid size-9 place-items-center rounded-lg text-xs font-semibold text-sidebar-foreground hover:bg-white/15 hover:text-white',
              current ? 'bg-sidebar-active text-white ring-2 ring-sidebar-bar' : 'bg-white/10',
            )}
          >
            {initialsOf(c.name)}
          </Link>
        )
      })}
    </section>
  )
}
