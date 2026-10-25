// The slim rail: always there on a desktop, 80px wide, the firm's few places with their names under
// the icons, then the clients opened lately as small discs, then the person. It looks the same whichever
// page you are on; only the highlighted place changes.

import { Link, useRouterState } from '@tanstack/react-router'
import { Activity, Bell, LayoutDashboard, Settings, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { AlertDot, useAlertDot } from '@/features/alerts/AlertBell'
import { clientIdOf } from '@/lib/modules'
import { useClientMemory } from '@/lib/recentClients'
import { JUMP_KEYS } from '@/lib/jump'
import { railActive, railHref, railItems, type RailItem } from '@/lib/sidebarNav'
import { initialsOf } from '@/lib/useDebounced'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { useClientNames } from './clientHeader'
import { UserMenu } from './UserMenu'

export const RAIL_ICONS: Record<RailItem['id'], ReactNode> = {
  dashboard: <LayoutDashboard strokeWidth={1.75} aria-hidden />,
  clients: <Users strokeWidth={1.75} aria-hidden />,
  alerts: <Bell strokeWidth={1.75} aria-hidden />,
  staff: <Activity strokeWidth={1.75} aria-hidden />,
  settings: <Settings strokeWidth={1.75} aria-hidden />,
}

const RECENT_SHOWN = 4

/** The tooltip: the place, and the key that goes there where there is one. */
function railTitle(item: RailItem): string {
  const jump = JUMP_KEYS.find((j) => j.module === (item.id === 'dashboard' ? 'dashboard' : item.id === 'clients' ? 'clients' : ''))
  const keys = jump ? ` (G ${jump.key.toUpperCase()})` : item.id === 'staff' ? ' (G W)' : item.id === 'settings' ? ' (G F)' : ''
  return `${item.label}${keys}`
}

export function Rail({ onShortcuts }: { onShortcuts: () => void }) {
  const { can } = useSession()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const clientId = clientIdOf(path)
  const items = railItems(can)
  const active = railActive(path)
  // A dot on Alerts when anything is open (red, amber or the brand colour by how serious); a number would only be noise here.
  const alertDot = useAlertDot()

  return (
    <div className="flex h-full w-20 flex-col items-center overflow-y-auto overscroll-contain border-r border-white/10 bg-sidebar py-3 text-sidebar-foreground [scrollbar-width:none]">
      <Link
        to={(items[0] ? railHref(items[0], can) : '/clients') as never}
        aria-label="AutoCA home"
        className="mb-3 grid size-9 shrink-0 place-items-center rounded-md bg-brand text-[13px] font-bold tracking-tight text-white"
      >
        CA
      </Link>
      <nav aria-label="Main" className="flex w-full flex-col items-center gap-1 px-2">
        {items.map((item) => {
          const isActive = active === item.id
          const dot = item.id === 'alerts' ? alertDot : null
          return (
            <Link
              key={item.id}
              to={railHref(item, can) as never}
              activeOptions={{ exact: true, includeSearch: false }}
              aria-current={isActive ? 'page' : undefined}
              aria-label={item.label}
              title={railTitle(item)}
              className={cn(
                'relative grid size-11 place-items-center rounded-md text-sidebar-foreground hover:bg-white/5 hover:text-white [&_svg]:size-[22px] [&_svg]:shrink-0',
                isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-2 before:-left-2 before:w-[3px] before:rounded-full before:bg-sidebar-bar',
              )}
            >
              {RAIL_ICONS[item.id]}
              {dot && <AlertDot level={dot} className="absolute right-2 top-2" />}
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
    <section aria-label="Recent clients" className="mt-3 flex w-full flex-col items-center gap-2 border-t border-white/10 px-2 pt-3">
      <h2 className="sr-only">Recent clients</h2>
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
              'grid size-9 place-items-center rounded-md text-xs font-semibold text-sidebar-foreground hover:bg-white/15 hover:text-white',
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
