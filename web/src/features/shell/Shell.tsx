// The shell: a slim rail for the firm's places, a client panel while a client is open, a top bar, the page.
//
// Which navigation shows depends on the address and nothing else: any path outside /clients/<id>/...
// is the firm's, a path inside it is that client's. Under 1024px the rail and panel become a drawer, and
// a client's five most-used screens a strip under the top bar. One of the two layouts is mounted at a time.

import { Link, Outlet, useNavigate, useRouterState, useSearch } from '@tanstack/react-router'
import { Menu, Search, Sparkles, X } from 'lucide-react'
import { Dialog as Drawer } from 'radix-ui'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { useAssistantShort } from '@/features/assistant/useAssistant'
import { Brand } from '@/features/auth/AuthLayout'
import { AlertBell, useAlertCount } from '@/features/alerts/AlertBell'
import { activeClientItem, clientScreenTitle } from '@/lib/clientNav'
import { fyLabel, financialYearOf } from '@/lib/format'
import { parseFy } from '@/lib/fy'
import { useHotkey } from '@/lib/hotkeys'
import { JUMP_KEYS, moduleHref, type JumpKey } from '@/lib/jump'
import { clientIdOf, moduleOf, type ModuleId } from '@/lib/modules'
import { railActive, railHref, railItems } from '@/lib/sidebarNav'
import { usePageTitle } from '@/lib/title'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { usePalette } from './CommandPalette'
import { ClientNavList, PanelHeader, ClientPanel } from './ClientPanel'
import { PhoneClientButton, ClientStrip } from './PhoneChrome'
import { Rail, RAIL_ICONS } from './Rail'
import { useRouteFocus } from './routeFocus'
import { ShortcutSheet } from './ShortcutSheet'
import { useFy } from './useFy'
import { UserMenu } from './UserMenu'

/** What the phone's top bar says in the firm's pages, where there is no client to name. */
const FIRM_TITLE: Partial<Record<ModuleId, string>> = {
  dashboard: 'Dashboard',
  clients: 'Clients',
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

/** The browser tab names the screen. Screens outside a client, and the GST screens (which name the run), set their own title. */
function useClientPageTitle() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const parts = path.split('/').filter(Boolean)
  const item = activeClientItem(path)
  const title = parts[0] !== 'clients' ? undefined : parts.length === 1 ? 'Clients' : item && item.screen !== 'gst' ? clientScreenTitle(item) : undefined
  usePageTitle(title)
}

/** Modules where the financial year in view means something under All clients. */
const FY_MODULES: ModuleId[] = ['dashboard', 'clients', 'pipeline', 'bookkeeping', 'bank', 'gst', 'reports']

/**
 * The financial year in view (April to March, named by the year it starts in). Inside a client it is
 * that client's remembered year, written to `?fy=`. Under All clients it is a firm-level year, also
 * carried in `?fy=`, and picking a client afterwards keeps it.
 */
function FySelect({ className }: { className?: string }) {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const { clientId, fy: clientFy, setFy: setClientFy, dataYears } = useFy()
  const search = useSearch({ strict: false }) as { fy?: unknown }
  const navigate = useNavigate()
  const module = moduleOf(path)
  if (!clientId && (!module || !FY_MODULES.includes(module))) return null

  const now = financialYearOf(new Date())
  const fy = clientId ? clientFy : (parseFy(search.fy) ?? now)
  const setFy = clientId
    ? setClientFy
    : (next: number) => void navigate({ to: '.', search: ((prev: Record<string, unknown>) => ({ ...prev, fy: next })) as never, replace: true })
  // A year that has not begun has no books to show, so the list starts at the current one.
  const years = new Set([...Array.from({ length: 8 }, (_, i) => now - i), ...dataYears, fy])
  return (
    <select
      aria-label="Financial year"
      value={fy}
      onChange={(e) => setFy(Number(e.target.value))}
      className={cn('h-9 shrink-0 rounded-md border border-input bg-card px-2.5 text-sm font-medium text-foreground', className)}
    >
      {[...years]
        .sort((a, b) => b - a)
        .map((year) => (
          <option key={year} value={year}>
            FY {fyLabel(year)}
          </option>
        ))}
    </select>
  )
}

function PaletteTrigger() {
  const palette = usePalette()
  return (
    <button
      type="button"
      onClick={() => palette.open()}
      className="flex h-9 min-w-0 max-w-sm flex-1 items-center gap-2 rounded-md border border-input bg-card px-3 text-sm text-faint hover:bg-hover"
    >
      <Search className="size-4 shrink-0" aria-hidden />
      <span className="truncate">Search or jump</span>
      <span className="ml-auto flex shrink-0 items-center gap-1">
        <Kbd>Ctrl</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  )
}

/**
 * The assistant's live state while a client is open: "Assistant reading 14 rows", "Assistant paused,
 * 32 s". It links to Review, where the rows are, and is announced politely as it changes. Nothing
 * shows when the assistant has nothing to do.
 */
function AssistantIndicator() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const clientId = clientIdOf(path)
  const text = useAssistantShort(clientId)
  return (
    <div role="status" aria-live="polite" className="max-md:hidden">
      {text && clientId && (
        <Link
          to="/clients/$clientId/review"
          params={{ clientId }}
          search={{ stage: 'all' }}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-input bg-info-bg px-2.5 text-[13px] font-medium text-info hover:bg-hover"
        >
          <Sparkles className="size-3.5" aria-hidden />
          {text}
        </Link>
      )}
    </div>
  )
}

/** `g` then a letter jumps to a module. Plain keys are ignored while a field has focus (the registry's rule). */
function JumpKeys() {
  const { can } = useSession()
  const navigate = useNavigate()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const clientId = clientIdOf(path)
  return (
    <>
      {JUMP_KEYS.map((jump) => (
        <JumpKeyBinding key={jump.key} jump={jump} allowed={can(jump.permission)} onGo={(to) => void navigate({ to: to as never })} clientId={clientId} />
      ))}
    </>
  )
}

function JumpKeyBinding({ jump, allowed, onGo, clientId }: { jump: JumpKey; allowed: boolean; onGo: (to: string) => void; clientId?: string }) {
  useHotkey(`g ${jump.key}`, jump.label, () => allowed && onGo(moduleHref(jump.module, clientId)), 'Go to')
  return null
}

/** Said once, at the top, while the browser has no network: nothing typed now would be saved. */
function OfflineStrip() {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])
  if (online) return null
  return (
    <div role="alert" className="no-print border-b border-accent-edge bg-accent px-4 py-2 text-center text-[13px] font-medium text-accent-foreground">
      You are offline. Changes cannot be saved until the connection is back.
    </div>
  )
}

/** The phone's menu: search, the year, the firm's places, then (inside a client) that client's screens and the person. */
function DrawerBody({ clientId, onClose, onShortcuts }: { clientId?: string; onClose: () => void; onShortcuts: () => void }) {
  const { can, me } = useSession()
  const palette = usePalette()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const active = railActive(path)
  const alertCount = useAlertCount(!clientId)
  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex items-center justify-between py-1.5 pl-4 pr-1.5 text-white">
        <Brand />
        <Drawer.Close asChild>
          <Button variant="ghost" size="icon" className="size-11 text-sidebar-foreground hover:bg-white/10 hover:text-white" aria-label="Close menu">
            <X />
          </Button>
        </Drawer.Close>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-4">
        <div className="grid gap-2 px-2 pb-2">
          <button
            type="button"
            onClick={() => {
              onClose()
              setTimeout(() => palette.open(), 150)
            }}
            className="flex h-11 items-center gap-2 rounded-md bg-white/10 px-3 text-sm text-sidebar-foreground hover:bg-white/15"
          >
            <Search className="size-4" aria-hidden /> Search or jump
          </button>
          <FySelect className="h-11 w-full border-white/20 bg-white/10 text-sidebar-foreground [&>option]:text-foreground" />
        </div>
        <nav aria-label="Main" className="px-2">
          <ul className="grid gap-0.5">
            {railItems(can).map((item) => {
              const isActive = active === item.id
              const count = item.id === 'alerts' ? alertCount : 0
              return (
                <li key={item.id}>
                  <Link
                    to={railHref(item, can) as never}
                    onClick={onClose}
                    activeOptions={{ exact: true, includeSearch: false }}
                    aria-current={isActive ? 'page' : undefined}
                    className={cn(
                      'relative flex h-11 items-center gap-3 rounded-md px-3 text-sm font-medium text-sidebar-foreground hover:bg-white/5 hover:text-white [&_svg]:size-[18px] [&_svg]:shrink-0',
                      isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-sidebar-bar',
                    )}
                  >
                    {RAIL_ICONS[item.id]}
                    {item.long}
                    {count > 0 && (
                      <span className="num ml-auto rounded-sm bg-sidebar-chip px-1.5 text-xs font-medium text-sidebar-chip-foreground">
                        {count}
                        <span className="sr-only"> need attention</span>
                      </span>
                    )}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>
        {clientId && (
          <section aria-label="This client" className="mt-3 border-t border-white/10 bg-sidebar-panel pb-2 pt-1">
            <PanelHeader clientId={clientId} />
            <ClientNavList clientId={clientId} touch onNavigate={onClose} />
          </section>
        )}
      </div>
      <div className="flex items-center gap-3 border-t border-white/10 px-3 py-2.5 text-xs text-sidebar-muted">
        <UserMenu variant="drawer" onShortcuts={onShortcuts} />
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-sidebar-foreground">{me?.full_name || me?.email}</div>
          <div className="truncate">{me?.role_display}</div>
        </div>
      </div>
    </div>
  )
}

export function Shell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const navigate = useNavigate()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const desktop = useMediaQuery('(min-width: 1024px)')
  const clientId = clientIdOf(path)

  useHotkey('?', 'Show keyboard shortcuts', () => setShortcutsOpen(true))
  const { can, me } = useSession()
  useClientPageTitle()
  useRouteFocus()
  useHotkey('g w', 'Go to staff performance', () => can('client.view') && void navigate({ to: '/staff' }), 'Go to')
  useHotkey('g t', 'Go to team & roles', () => can('team.view') && void navigate({ to: '/settings/team' }), 'Go to')
  useHotkey('g f', 'Go to firm settings', () => can('firm.manage') && void navigate({ to: '/settings/firm' }), 'Go to')

  // The drawer closes when the person navigates, and when the window grows into the desktop layout.
  useEffect(() => setMenuOpen(false), [path])
  useEffect(() => {
    if (desktop) setMenuOpen(false)
  }, [desktop])

  const module = moduleOf(path)
  const firmName = me?.firm?.name

  return (
    <div className="flex min-h-svh">
      <a
        href="#content"
        onClick={(e) => {
          e.preventDefault()
          document.getElementById('content')?.focus()
        }}
        className="sr-only z-[60] rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>

      {desktop && (
        <>
          <aside aria-label="Firm" className="no-print sticky top-0 h-svh w-[72px] shrink-0">
            <Rail onShortcuts={() => setShortcutsOpen(true)} />
          </aside>
          {clientId && (
            <aside aria-label="Client" className="no-print sticky top-0 h-svh w-[216px] shrink-0">
              <ClientPanel key={clientId} clientId={clientId} />
            </aside>
          )}
        </>
      )}

      {!desktop && (
        <Drawer.Root open={menuOpen} onOpenChange={setMenuOpen}>
          <Drawer.Portal>
            <Drawer.Overlay className="fixed inset-0 z-40 bg-black/45 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms]" />
            <Drawer.Content
              aria-describedby={undefined}
              className="fixed inset-y-0 left-0 z-50 w-80 max-w-[88vw] outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms]"
            >
              <Drawer.Title className="sr-only">Menu</Drawer.Title>
              <DrawerBody clientId={clientId} onClose={() => setMenuOpen(false)} onShortcuts={() => setShortcutsOpen(true)} />
            </Drawer.Content>
          </Drawer.Portal>
        </Drawer.Root>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineStrip />
        <header className="no-print sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background px-2 sm:px-3 md:gap-3 lg:px-6">
          {clientId && <div className="absolute inset-x-0 top-0 h-[3px] bg-brand" aria-hidden />}
          {desktop ? (
            <>
              {!clientId && (
                <span className="hidden shrink-0 truncate text-[13px] font-medium text-muted-foreground xl:block">
                  {firmName ? `${firmName} · All clients` : 'All clients'}
                </span>
              )}
              <FySelect />
              <PaletteTrigger />
              <div className="ml-auto flex shrink-0 items-center gap-3">
                <AssistantIndicator />
                <AlertBell key={`bell-${clientId ?? "firm"}`} clientId={clientId} />
                <UserMenu onShortcuts={() => setShortcutsOpen(true)} />
              </div>
            </>
          ) : (
            <>
              <Button variant="ghost" size="icon" className="size-11 shrink-0" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
                <Menu />
              </Button>
              {clientId ? (
                <PhoneClientButton key={clientId} clientId={clientId} />
              ) : (
                <div className="min-w-0 flex-1 truncate px-1 text-base font-semibold text-heading">{(module && FIRM_TITLE[module]) || 'AutoCA'}</div>
              )}
              <AlertBell key={`bell-${clientId ?? "firm"}`} clientId={clientId} />
            </>
          )}
        </header>
        {!desktop && clientId && <ClientStrip clientId={clientId} />}
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-[1400px] flex-1 p-4 outline-none md:p-6">
          <Outlet />
        </main>
      </div>

      <JumpKeys />
      <ShortcutSheet open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </div>
  )
}
