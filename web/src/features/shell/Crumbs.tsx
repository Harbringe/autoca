// The context bar: where you are, as a path you can walk. Firm, then the client, then the financial year in view, then the place inside the
// client (Bank statements), then the tab of that place (Review). Each step that has neighbours is a menu, so the whole path is changeable
// from the keyboard: Tab to a step, Enter or the Down arrow to open it, arrows to choose, Enter to go, Esc to close.

import { Link, useRouterState } from '@tanstack/react-router'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { CLIENT_KEYS, activeClientItem, clientNavFor, clientScreenOf, clientScreenPath, clientTabsFor } from '@/lib/clientNav'
import { moduleHref } from '@/lib/jump'
import { moduleOf, type ModuleId } from '@/lib/modules'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { ClientSwitcher } from './ClientSwitcher'
import { useClientHeader } from './clientHeader'
import { FySelect } from './FySelect'

/** What the firm's own pages are called in the path. */
const FIRM_PAGE: Partial<Record<ModuleId, string>> = {
  dashboard: 'Dashboard',
  clients: 'All clients',
  pipeline: 'Work pipeline',
  alerts: 'Alerts',
  staff: 'Staff performance',
  settings: 'Settings',
  documents: 'Documents',
  bookkeeping: 'Bookkeeping',
  bank: 'Bank statements',
  reports: 'Reports',
  gst: 'GST reconciliation',
}

const step = 'inline-flex h-9 max-w-[15rem] items-center gap-1.5 rounded-md px-2 text-sm hover:bg-hover'
const Sep = () => <ChevronRight className="size-3.5 shrink-0 text-faint" aria-hidden />

/** The key shown beside a menu entry, as small keys. */
function Keys({ combo }: { combo?: string }) {
  if (!combo) return null
  return (
    <span aria-hidden className="ml-auto flex shrink-0 gap-0.5 pl-6 text-[11px] font-semibold uppercase text-muted-foreground">
      {combo.split(' ').map((k) => (
        <kbd key={k} className="rounded-sm border px-1 font-sans">
          {k}
        </kbd>
      ))}
    </span>
  )
}

/** A step of the path that opens a list of its neighbours. */
function StepMenu({ label, current, items, last }: { label: string; current: string; items: { id: string; label: string; to: string; combo?: string; active: boolean }[]; last?: boolean }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`${label}: ${current}. Change`}
          aria-current={last ? 'page' : undefined}
          className={cn(step, last ? 'font-semibold text-heading' : 'text-muted-foreground hover:text-foreground')}
        >
          <span className="truncate">{current}</span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" aria-label={label} className="min-w-56">
        {items.map((item) => (
          <DropdownMenuItem key={item.id} asChild>
            <Link to={item.to as never} aria-current={item.active ? 'page' : undefined} className={cn(item.active && 'font-semibold text-heading')}>
              <span className="truncate">{item.label}</span>
              <Keys combo={item.combo} />
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ClientStep({ clientId, last }: { clientId: string; last: boolean }) {
  const { name } = useClientHeader(clientId)
  return (
    <ClientSwitcher currentId={clientId}>
      <button
        type="button"
        aria-label={`Client: ${name ?? ''}. Switch client`}
        aria-keyshortcuts="Alt+C"
        title="Switch client (Alt C)"
        aria-current={last ? 'page' : undefined}
        className={cn(step, 'max-w-[16rem] font-semibold text-heading')}
      >
        <span className="truncate">{name ?? '…'}</span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </button>
    </ClientSwitcher>
  )
}

/** The places inside the open client, and the tabs of the place the address is on. */
function InsideClient({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const { items, bottom } = clientNavFor(can)
  const place = activeClientItem(path)
  const screen = clientScreenOf(path)
  const tabs = clientTabsFor(path, can)
  const tab = tabs.find((t) => t.screen === screen)
  if (!place) return null
  return (
    <>
      <Sep />
      <StepMenu
        label="Place"
        current={place.label}
        last={!tab}
        items={[...items, ...bottom].map((i) => ({ id: i.screen || 'overview', label: i.label, to: clientScreenPath(clientId, i.screen), combo: CLIENT_KEYS[i.screen], active: i === place }))}
      />
      {tabs.length > 1 && tab && (
        <>
          <Sep />
          <StepMenu
            label={`${place.label} section`}
            current={tab.label}
            last
            items={tabs.map((t) => ({ id: t.screen, label: t.label, to: clientScreenPath(clientId, t.screen), combo: CLIENT_KEYS[t.screen], active: t.screen === screen }))}
          />
        </>
      )}
    </>
  )
}

/**
 * Firm › Client › FY › Place › Section. Under All clients it is Firm › the page, then the year where the page has one.
 * It is a landmark of its own, and its last step is the page you are on.
 */
export function ContextBar({ clientId, firmName }: { clientId?: string; firmName?: string }) {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const module = moduleOf(path)
  return (
    <nav aria-label="Where you are" className="flex min-w-0 items-center gap-0.5 overflow-hidden text-sm">
      {firmName && (
        <>
          <Link to={moduleHref('dashboard') as never} className={cn(step, 'max-xl:hidden text-muted-foreground hover:text-foreground')} title="Dashboard (G D)">
            <span className="truncate">{firmName}</span>
          </Link>
          <span className="max-xl:hidden">
            <Sep />
          </span>
        </>
      )}
      {clientId ? (
        <>
          <ClientStep clientId={clientId} last={false} />
          <FySelect crumb />
          <InsideClient clientId={clientId} />
        </>
      ) : (
        <>
          <span aria-current="page" className={cn(step, 'font-semibold text-heading hover:bg-transparent')}>
            <span className="truncate">{(module && FIRM_PAGE[module]) || 'All clients'}</span>
          </span>
          <FySelect crumb />
        </>
      )}
    </nav>
  )
}
