// The client panel: the second column, only while a client is open. The client's full name and where
// its books stand, a star to pin it, and the places of that client (Bank statements, Bookkeeping, ...); the closely related
// screens of a place are tabs on its page. Where you are is always visible.

import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import { ChevronsUpDown, PanelLeftClose, Star } from 'lucide-react'
import { reviewSummary } from '@/api/queries/clients'
import { activeClientItem, CLIENT_GROUPS, CLIENT_KEYS, clientNavFor, clientScreenPath } from '@/lib/clientNav'
import { toggleClientPin, useClientMemory } from '@/lib/recentClients'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { useClientHeader } from './clientHeader'
import { ClientSwitcher } from './ClientSwitcher'
import { Kbd } from '@/components/ui/kbd'
import { toggleSidebar } from './useSidebar'

const chip = 'num ml-auto shrink-0 rounded-sm bg-sidebar-chip px-1.5 text-xs font-medium text-sidebar-chip-foreground'

/** This client's count of rows waiting, for the Review item. Zero when the person may not see transactions. */
export function useReviewCount(clientId: string): number | undefined {
  const { can } = useSession()
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  return summary.data?.total
}

/** The list itself, used by the desktop panel and, with bigger rows, by the phone's drawer. */
export function ClientNavList({ clientId, touch = false, part = 'all', onNavigate }: { clientId: string; touch?: boolean; part?: 'all' | 'main' | 'bottom'; onNavigate?: () => void }) {
  const { can } = useSession()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const reviewCount = useReviewCount(clientId)
  const { items, bottom } = clientNavFor(can)
  const active = activeClientItem(path)

  const link = (item: (typeof items)[number]) => {
    const isActive = active === item
    const hasCount = item.screen === 'statements' && !!reviewCount
    // An item that carries a count has no room for the key beside it; the key is in the path menu and in the shortcut sheet.
    const keys = hasCount ? undefined : CLIENT_KEYS[item.screen]
    return (
      <li key={item.screen || 'overview'}>
        <Link
          to={clientScreenPath(clientId, item.screen) as never}
          onClick={onNavigate}
          activeOptions={{ exact: true, includeSearch: false }}
          aria-current={isActive ? 'page' : undefined}
          aria-keyshortcuts={keys}
          className={cn(
            'group/nav relative flex items-center gap-3 rounded-md px-3 text-sm font-medium text-sidebar-foreground hover:bg-white/5 hover:text-white',
            touch ? 'h-11' : 'h-9',
            isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-sidebar-bar',
          )}
        >
          <item.icon className="size-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
          <span className="truncate">{item.label}</span>
          {/* The key that opens it, shown while the pointer or the keyboard is on the item, so the hint is there when it is wanted. */}
          {keys && !touch && (
            <span aria-hidden className="ml-auto hidden shrink-0 items-center gap-0.5 text-[11px] font-semibold uppercase text-sidebar-muted group-hover/nav:flex group-focus-visible/nav:flex">
              {keys.split(' ').map((k) => (
                <kbd key={k} className="rounded-sm border border-white/15 px-1 font-sans">
                  {k}
                </kbd>
              ))}
            </span>
          )}
          {hasCount ? (
            <span className={chip}>
              {reviewCount}
              <span className="sr-only"> rows waiting</span>
            </span>
          ) : null}
        </Link>
      </li>
    )
  }

  if (part === 'bottom') return bottom.length > 0 ? <ul aria-label="Client profile" className="grid gap-0.5 px-2">{bottom.map(link)}</ul> : null
  return (
    <nav aria-label="Client screens" className="grid gap-0 px-2">
      {CLIENT_GROUPS.map((group) => {
        const inGroup = items.filter((i) => i.group === group.id)
        if (inGroup.length === 0) return null
        return (
          <section key={group.id} aria-labelledby={`nav-${group.id}`} className="mt-1">
            <h2 id={`nav-${group.id}`} className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">
              {group.label}
            </h2>
            <ul className="grid gap-0.5">{inGroup.map(link)}</ul>
          </section>
        )
      })}
      {part === 'all' && bottom.length > 0 && <ul className="mt-3 grid gap-0.5 border-t border-white/10 pt-2">{bottom.map(link)}</ul>}
    </nav>
  )
}

/** The name, the year and state, the pin and the way to another client. */
export function PanelHeader({ clientId }: { clientId: string }) {
  const { name, line } = useClientHeader(clientId)
  const { pinned } = useClientMemory()
  const isPinned = pinned.includes(clientId)
  return (
    <div className="relative px-2 pb-2">
      <ClientSwitcher currentId={clientId}>
        <button
          type="button"
          aria-label={`${name ?? 'Client'}${line ? `, ${line}` : ''}. Switch client`}
          aria-keyshortcuts="Alt+C"
          title="Switch client (Alt C)"
          className="relative flex w-full items-start gap-3 rounded-lg bg-white/5 py-3 pl-3 pr-10 text-left hover:bg-white/10"
        >
          <span className="grid size-8 shrink-0 place-items-center rounded-md bg-white/10 text-sm font-semibold text-sidebar-foreground" aria-hidden>
            {name?.trim().charAt(0).toUpperCase() || '·'}
          </span>
          <span className="min-w-0 flex-1">
            <span className="line-clamp-3 break-words text-sm font-semibold leading-5 text-white">{name ?? '…'}</span>
            <span className="mt-0.5 block text-xs leading-4 text-sidebar-muted">{line}</span>
          </span>
          <ChevronsUpDown className="pointer-events-none absolute bottom-3.5 right-3 size-4 text-sidebar-muted" strokeWidth={1.75} aria-hidden />
        </button>
      </ClientSwitcher>
      <button
        type="button"
        aria-pressed={isPinned}
        aria-label={isPinned ? 'Unpin this client' : 'Pin this client'}
        title={isPinned ? 'Unpin this client' : 'Pin this client to the switcher'}
        onClick={() => toggleClientPin(clientId)}
        className="absolute right-3 top-3.5 grid size-7 place-items-center rounded-md text-sidebar-muted hover:bg-white/10 hover:text-white"
      >
        <Star className={cn('size-4', isPinned && 'fill-current text-sidebar-chip-foreground')} strokeWidth={1.75} aria-hidden />
      </button>
    </div>
  )
}

export function ClientPanel({ clientId }: { clientId: string }) {
  return (
    <div className="flex h-full w-[232px] flex-col border-r border-white/10 bg-sidebar text-sidebar-foreground">
      <div className="flex items-center justify-between px-4 pb-2 pt-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">Client</h2>
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label="Hide the client menu"
          aria-keyshortcuts="Control+B"
          title="Hide the client menu (Ctrl B)"
          className="grid size-7 place-items-center rounded-md text-sidebar-muted hover:bg-white/10 hover:text-white"
        >
          <PanelLeftClose className="size-4" strokeWidth={1.75} aria-hidden />
        </button>
      </div>
      <PanelHeader clientId={clientId} />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-3">
        <ClientNavList clientId={clientId} part="main" />
      </div>
      <div className="shrink-0 border-t border-white/10 py-2">
        <ClientNavList clientId={clientId} part="bottom" />
        <p className="mt-1 flex items-center gap-1.5 px-5 pt-1 text-[11px] text-sidebar-muted">
          <Kbd className="border-white/15 bg-transparent text-sidebar-muted">?</Kbd> for every shortcut
        </p>
      </div>
    </div>
  )
}
