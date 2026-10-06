// The client panel: the second column, only while a client is open. The client's full name and where
// its books stand, a star to pin it, and every screen of that client in one flat list in the order the
// work goes. No folding: where you are is always visible, and the panel scrolls on its own if it must.

import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import { ChevronsUpDown, Star } from 'lucide-react'
import { reviewSummary } from '@/api/queries/clients'
import { activeClientItem, clientNavFor, clientScreenPath } from '@/lib/clientNav'
import { toggleClientPin, useClientMemory } from '@/lib/recentClients'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { useClientHeader } from './clientHeader'
import { ClientSwitcher } from './ClientSwitcher'

const chip = 'num ml-auto rounded-sm bg-sidebar-chip px-1.5 text-xs font-medium text-sidebar-chip-foreground'

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
    return (
      <li key={item.screen || 'overview'}>
        <Link
          to={clientScreenPath(clientId, item.screen) as never}
          onClick={onNavigate}
          activeOptions={{ exact: true, includeSearch: false }}
          aria-current={isActive ? 'page' : undefined}
          className={cn(
            'relative flex items-center rounded-md px-3 text-sm font-medium text-sidebar-foreground hover:bg-white/5 hover:text-white',
            touch ? 'h-11' : 'h-8',
            isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-sidebar-bar',
          )}
        >
          <span className="truncate">{item.label}</span>
          {item.screen === 'review' && reviewCount ? (
            <span className={chip}>
              {reviewCount}
              <span className="sr-only"> rows waiting</span>
            </span>
          ) : null}
        </Link>
      </li>
    )
  }

  // Blocks: the items up to the next divider label.
  const blocks: { label?: string; items: typeof items }[] = []
  for (const item of items) {
    if (item.section || blocks.length === 0) blocks.push({ label: item.section, items: [item] })
    else blocks[blocks.length - 1]!.items.push(item)
  }

  if (part === 'bottom') return bottom.length > 0 ? <ul aria-label="Client settings" className="grid gap-0.5 px-2">{bottom.map(link)}</ul> : null
  return (
    <nav aria-label="Client screens" className="grid gap-0 px-2">
      {blocks.map((block, i) => (
        <div key={block.label ?? i} role={block.label ? 'group' : undefined} aria-label={block.label}>
          {block.label && (
            <div aria-hidden className={cn('px-3 pb-0.5 text-[11px] font-medium uppercase tracking-[0.06em] text-sidebar-muted', i === 0 ? 'pt-0.5' : 'pt-2')}>
              {block.label}
            </div>
          )}
          <ul className="grid">{block.items.map(link)}</ul>
        </div>
      ))}
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
    <div className="relative px-2 pb-1.5 pt-2.5">
      <ClientSwitcher currentId={clientId}>
        <button
          type="button"
          aria-label={`${name ?? 'Client'}${line ? `, ${line}` : ''}. Switch client`}
          className="block w-full rounded-md px-2 py-1 text-left hover:bg-white/5"
        >
          <span className="block break-words pr-7 text-[15px] font-semibold leading-5 text-white">{name ?? '…'}</span>
          <span className="mt-1 flex items-center gap-1 text-xs text-sidebar-muted">
            <span className="min-w-0 flex-1">{line}</span>
            <ChevronsUpDown className="size-3.5 shrink-0" aria-hidden />
          </span>
        </button>
      </ClientSwitcher>
      <button
        type="button"
        aria-pressed={isPinned}
        aria-label={isPinned ? 'Unpin this client' : 'Pin this client'}
        title={isPinned ? 'Unpin this client' : 'Pin this client to the switcher'}
        onClick={() => toggleClientPin(clientId)}
        className="absolute right-2.5 top-3 grid size-7 place-items-center rounded-md text-sidebar-muted hover:bg-white/10 hover:text-white"
      >
        <Star className={cn('size-4', isPinned && 'fill-current text-sidebar-chip-foreground')} aria-hidden />
      </button>
    </div>
  )
}

export function ClientPanel({ clientId }: { clientId: string }) {
  return (
    <div className="flex h-full w-[216px] flex-col border-r border-white/5 bg-sidebar-panel text-sidebar-foreground">
      <div className="h-[3px] shrink-0 bg-sidebar-bar" aria-hidden />
      <PanelHeader clientId={clientId} />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-3">
        <ClientNavList clientId={clientId} part="main" />
      </div>
      <div className="shrink-0 border-t border-white/10 py-1.5">
        <ClientNavList clientId={clientId} part="bottom" />
      </div>
    </div>
  )
}
