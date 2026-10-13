// The shell: a slim rail for the firm's places, a client panel while a client is open, a top bar, the page.
//
// Which navigation shows depends on the address and nothing else: any path outside /clients/<id>/...
// is the firm's, a path inside it is that client's. Under 1024px the rail and panel become a drawer, and
// a client's five most-used screens a strip under the top bar. One of the two layouts is mounted at a time.

import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { Keyboard, Loader2, Menu, PanelLeftOpen, Search, X } from 'lucide-react'
import { Sparkles } from '@/components/ui/sparkles'
import { Dialog as Drawer } from 'radix-ui'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { useSavingMark } from '@/api/pending'
import { isProcessing } from '@/features/assistant/queue'
import { useAssistantShort, useAssistantStatus } from '@/features/assistant/useAssistant'
import { Brand } from '@/features/auth/AuthLayout'
import { AlertBell, useAlertCount } from '@/features/alerts/AlertBell'
import { clientScreenName, parentPath } from '@/lib/clientNav'
import { useHotkey } from '@/lib/hotkeys'
import { JUMP_KEYS, moduleHref, type JumpKey } from '@/lib/jump'
import { clientIdOf, moduleOf, type ModuleId } from '@/lib/modules'
import { railActive, railHref, railItems } from '@/lib/sidebarNav'
import { usePageTitle } from '@/lib/title'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { ContextBar } from './Crumbs'
import { FySelect } from './FySelect'
import { toggleSidebar, useSidebarHidden } from './useSidebar'
import { usePalette } from './CommandPalette'
import { ClientNavList, PanelHeader, ClientPanel } from './ClientPanel'
import { PhoneClientButton, ClientStrip } from './PhoneChrome'
import { Rail, RAIL_ICONS } from './Rail'
import { useRouteFocus } from './routeFocus'
import { ShortcutSheet } from './ShortcutSheet'
import { UserMenu } from './UserMenu'

/**
 * F6 and Shift+F6 move focus between the parts of the screen: the firm's rail, the client's menu, the top bar and the page. It is the key
 * Windows and code editors already use for this, so a person who lives on the keyboard never has to Tab through a whole menu to get across.
 */
function moveRegion(step: 1 | -1) {
  const regions = [...document.querySelectorAll<HTMLElement>('[data-region]')].filter((el) => el.offsetParent !== null || el.tagName === 'MAIN')
  if (regions.length === 0) return
  const here = regions.findIndex((el) => el.contains(document.activeElement))
  const next = regions[(here + step + regions.length) % regions.length]!
  const target = next.matches('main') ? next : (next.querySelector<HTMLElement>('[aria-current="page"], a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])') ?? next)
  target.focus()
}

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
  const title = parts[0] !== 'clients' ? undefined : parts.length === 1 ? 'Clients' : clientScreenName(path)
  usePageTitle(title)
}

/** The thin line along the top of the bar while a client is open. It sweeps while the assistant is reading that client's rows. */
function Ribbon({ clientId }: { clientId: string }) {
  const working = isProcessing(useAssistantStatus(clientId))
  return (
    <div className="absolute inset-x-0 top-0 h-[3px] overflow-hidden bg-brand" aria-hidden>
      {working && <span className="ribbon-sweep absolute inset-y-0 left-0 w-1/5" />}
    </div>
  )
}

function PaletteTrigger() {
  const palette = usePalette()
  return (
    <button
      type="button"
      onClick={() => palette.open()}
      aria-keyshortcuts="Control+K"
      title="Search or jump (Ctrl K)"
      className="grid h-9 w-full min-w-0 grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-md border border-input bg-muted/50 px-3 text-sm text-muted-foreground hover:bg-hover hover:text-foreground"
    >
      <span aria-hidden />
      <span className="flex min-w-0 items-center gap-2">
        <Search className="size-4 shrink-0" aria-hidden />
        <span className="truncate">Search or jump</span>
      </span>
      <span aria-hidden className="flex shrink-0 items-center justify-end gap-1">
        <Kbd>Ctrl</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  )
}

/**
 * "Saving…" while a change is on its way to the server. A change that takes longer than a quarter of a second shows it; it is
 * announced politely and never blocks anything, so the screen stays usable underneath.
 */
function SavingMark() {
  const shown = useSavingMark()
  return (
    <div role="status" aria-live="polite">
      {shown && (
        <span className="inline-flex h-8 items-center gap-1.5 rounded-md border border-input bg-card px-2.5 text-[13px] font-medium text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          Saving…
        </span>
      )}
    </div>
  )
}

/**
 * The assistant, while a client is open and it has something to do: a small calm mark, a spark and one word. What it is doing and how
 * far it has got is shown where it happens (in the Review rows and in the strip), so nothing here competes for the bar. The full state
 * ("Assistant processing 6 rows", "Assistant not answering") is still announced politely as it changes, and the mark links to Review.
 */
function AssistantIndicator() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const clientId = clientIdOf(path)
  const text = useAssistantShort(clientId)
  const status = useAssistantStatus(clientId)
  // Working or waiting is quiet (the rows show the work). A used allowance or an outage keeps its words, in amber, because a person should know.
  const needsWords = status.reason === 'daily_limit' || status.reason === 'provider_down'
  return (
    <div role="status" aria-live="polite" className="max-md:hidden">
      {text && clientId && (
        <Link
          to="/clients/$clientId/review"
          params={{ clientId }}
          search={{ stage: 'all' }}
          title={text}
          className={cn(
            'inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium hover:bg-hover',
            needsWords ? 'border-accent-edge bg-accent text-accent-foreground' : 'border-border bg-card text-muted-foreground',
          )}
        >
          <Sparkles working={status.state === 'working'} className="size-4" />
          {needsWords ? (
            text
          ) : (
            <>
              Assistant
              <span className="sr-only">: {text}</span>
            </>
          )}
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
  const alertCount = useAlertCount(false)
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
                      'relative flex h-11 items-center gap-2.5 rounded-md px-3 text-sm font-medium text-sidebar-foreground hover:bg-white/5 hover:text-white [&_svg]:size-4 [&_svg]:shrink-0',
                      isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-sidebar-bar',
                    )}
                  >
                    {RAIL_ICONS[item.id]}
                    <span className="truncate">{item.long}</span>
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
          <section aria-label="This client" className="mt-3 border-t border-white/10 pb-2 pt-1">
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
  const sidebarHidden = useSidebarHidden()
  useHotkey('ctrl+b', 'Show or hide the client menu', () => clientId && toggleSidebar())
  useHotkey('f6', 'Move to the next part of the screen (menu, top bar, page)', () => moveRegion(1))
  useHotkey('shift+f6', 'Move to the previous part of the screen', () => moveRegion(-1))
  useHotkey('alt+arrowup', 'Up one level in the path (section, place, client)', () => {
    const up = parentPath(path)
    if (up) void navigate({ to: up as never })
  })
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
          <aside aria-label="Firm" data-region="firm" className="no-print sticky top-0 h-svh w-20 shrink-0">
            <Rail onShortcuts={() => setShortcutsOpen(true)} />
          </aside>
          {clientId && !sidebarHidden && (
            <aside aria-label="Client" data-region="client" className="no-print sticky top-0 h-svh w-[232px] shrink-0">
              <ClientPanel key={clientId} clientId={clientId} />
            </aside>
          )}
        </>
      )}

      {!desktop && (
        <Drawer.Root open={menuOpen} onOpenChange={setMenuOpen}>
          <Drawer.Portal>
            <Drawer.Overlay className="fixed inset-0 z-40 bg-black/45 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0 duration-200" />
            <Drawer.Content
              aria-describedby={undefined}
              className="fixed inset-y-0 left-0 z-50 w-80 max-w-[88vw] outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left duration-200"
            >
              <Drawer.Title className="sr-only">Menu</Drawer.Title>
              <DrawerBody clientId={clientId} onClose={() => setMenuOpen(false)} onShortcuts={() => setShortcutsOpen(true)} />
            </Drawer.Content>
          </Drawer.Portal>
        </Drawer.Root>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineStrip />
        <header
          aria-label="Top bar"
          data-region="header"
          className={cn(
            'no-print sticky top-0 z-30 h-14 items-center gap-2 border-b bg-background px-2 sm:px-3 md:gap-3 lg:px-6',
            // Wide enough: the path on the left, the command bar centred as in a code editor, the person's tools on the right.
            desktop ? 'grid grid-cols-[minmax(0,1fr)_minmax(16rem,36rem)_minmax(0,1fr)]' : 'flex',
          )}
        >
          {clientId && <Ribbon clientId={clientId} />}
          {desktop ? (
            <>
              <div className="flex min-w-0 items-center gap-1">
                {clientId && sidebarHidden && (
                  <Button variant="ghost" size="icon" className="size-9 shrink-0" aria-label="Show the client menu" aria-keyshortcuts="Control+B" title="Show the client menu (Ctrl B)" onClick={toggleSidebar}>
                    <PanelLeftOpen className="size-[18px]" aria-hidden />
                  </Button>
                )}
                <ContextBar clientId={clientId} firmName={firmName} />
              </div>
              <PaletteTrigger />
              <div className="flex min-w-0 shrink-0 items-center justify-end gap-2">
                <SavingMark />
                <AssistantIndicator />
                <Button variant="ghost" size="icon" className="size-9 shrink-0" aria-label="Keyboard shortcuts" aria-keyshortcuts="?" title="Keyboard shortcuts (?)" onClick={() => setShortcutsOpen(true)}>
                  <Keyboard className="size-[18px]" aria-hidden />
                </Button>
                {clientId && <AlertBell key={`bell-${clientId}`} clientId={clientId} />}
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
              <div className="ml-auto"><SavingMark /></div>
              {clientId && <AlertBell key={`bell-${clientId}`} clientId={clientId} />}
            </>
          )}
        </header>
        {!desktop && clientId && <ClientStrip clientId={clientId} />}
        <main id="content" data-region="page" tabIndex={-1} className="mx-auto w-full max-w-[1920px] flex-1 p-4 outline-none md:p-6 2xl:px-10">
          {/* A new place fades in; moving between a client's own screens is handled inside the client, so its header stays put. */}
          <div key={path.split('/')[1] ?? ''} className="page-in">
            <Outlet />
          </div>
        </main>
      </div>

      <JumpKeys />
      <ShortcutSheet open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </div>
  )
}
