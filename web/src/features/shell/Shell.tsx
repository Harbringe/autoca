// The shell: a module sidebar, a top bar that says whose books you are in, and the page.
//
// The sidebar mirrors the product's map (Overview, Workflow, Accounting, Assurance, Intelligence,
// Management). Modules that are not built are real links to a "Coming soon" page, marked with a
// "Soon" chip. The active module is derived from the address. Under 1024px the sidebar is a drawer.

import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useParams, useRouterState, useSearch } from '@tanstack/react-router'
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  Building2,
  CalendarCheck,
  Calculator,
  ChevronsUpDown,
  Columns3,
  FileSpreadsheet,
  FolderOpen,
  Keyboard,
  Landmark,
  LayoutDashboard,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Rows3,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  TrendingUp,
  Users,
  EyeOff,
} from 'lucide-react'
import { Dialog as Drawer } from 'radix-ui'
import { useEffect, useState, type ReactNode } from 'react'
import { clientDetail, reviewSummary } from '@/api/queries/clients'
import { firmOverview } from '@/api/queries/overview'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Kbd } from '@/components/ui/kbd'
import { useAssistantShort } from '@/features/assistant/useAssistant'
import { Brand } from '@/features/auth/AuthLayout'
import { fyLabel, financialYearOf } from '@/lib/format'
import { parseFy } from '@/lib/fy'
import { useHotkey } from '@/lib/hotkeys'
import { JUMP_KEYS, moduleHref, type JumpKey } from '@/lib/jump'
import { clientIdOf, moduleOf, type ModuleId } from '@/lib/modules'
import { usePreferences, type Density, type Theme } from '@/lib/preferences'
import { usePageTitle } from '@/lib/title'
import { useRouteFocus } from './routeFocus'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { usePalette } from './CommandPalette'
import { ShortcutSheet } from './ShortcutSheet'
import { useFy } from './useFy'

interface NavEntry {
  id: ModuleId
  label: string
  icon: ReactNode
  /** Shown only to people holding this permission. */
  permission?: string
  /** No screen yet: the link goes to /soon/<id>. */
  soon?: boolean
}

const GROUPS: { label: string; items: NavEntry[] }[] = [
  {
    label: 'Overview',
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard />, permission: 'client.view' },
      { id: 'clients', label: 'Clients', icon: <Users />, permission: 'client.view' },
    ],
  },
  {
    label: 'Workflow',
    items: [
      { id: 'pipeline', label: 'Work pipeline', icon: <Columns3 />, permission: 'client.view' },
      { id: 'documents', label: 'Documents', icon: <FolderOpen />, permission: 'document.view' },
    ],
  },
  {
    label: 'Accounting',
    items: [
      { id: 'bookkeeping', label: 'Bookkeeping', icon: <BookOpen />, permission: 'report.view' },
      { id: 'bank', label: 'Bank statements', icon: <Landmark />, permission: 'transaction.view' },
      { id: 'gst', label: 'GST reconciliation', icon: <FileSpreadsheet />, permission: 'gst.view' },
      { id: 'taxation', label: 'Taxation / ITR', icon: <Calculator />, soon: true },
    ],
  },
  {
    label: 'Assurance',
    items: [
      { id: 'audit', label: 'Audit', icon: <ShieldCheck />, soon: true },
      { id: 'compliance', label: 'Compliance', icon: <CalendarCheck />, soon: true },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { id: 'reports', label: 'Reports', icon: <BarChart3 />, permission: 'report.view' },
      { id: 'ai', label: 'AI assistant', icon: <Sparkles />, soon: true },
      { id: 'analytics', label: 'Firm analytics', icon: <TrendingUp />, soon: true },
    ],
  },
  {
    label: 'Management',
    items: [
      { id: 'staff', label: 'Staff performance', icon: <Activity />, permission: 'client.view' },
      { id: 'notifications', label: 'Notifications', icon: <Bell />, soon: true },
      { id: 'settings', label: 'Settings', icon: <Settings /> },
    ],
  },
]

const SCREEN_TITLE: Record<string, string> = {
  documents: 'Documents',
  bookkeeping: 'Books overview',
  statements: 'Statements',
  review: 'Review',
  bills: 'Purchases & Sales',
  daybook: 'Day Book',
  'open-items': 'To fix',
  invoices: 'Invoices',
  tds: 'TDS',
  assets: 'Assets',
  ledgers: 'Ledgers',
  reports: 'Reports',
  books: 'Books & sign-off',
  masters: 'Parties & rules',
  team: 'Settings & team',
}

/** The browser tab names the screen. Screens outside a client, and the GST screens (which name the run), set their own title. */
function useClientPageTitle() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const parts = path.split('/').filter(Boolean)
  const title = parts[0] !== 'clients' ? undefined : parts.length === 1 ? 'Clients' : parts.length === 2 ? 'Client profile' : (SCREEN_TITLE[parts[2]!] ?? undefined)
  usePageTitle(title)
}

/** The small champagne chip on the dark sidebar: "Soon", or a real count. */
const chip = 'ml-auto rounded-sm bg-sidebar-chip px-1.5 text-xs font-medium text-sidebar-chip-foreground'

function useSidebarCount(): number | undefined {
  const { can } = useSession()
  const { clientId } = useParams({ strict: false }) as { clientId?: string }
  const one = useQuery({ ...reviewSummary(clientId ?? ''), enabled: !!clientId && can('transaction.view') })
  // The firm total is the overview's own total: one request, the same clients the list shows.
  const firm = useQuery({ ...firmOverview(), enabled: !clientId })
  if (clientId) return one.data?.total
  if (!firm.data) return undefined
  return firm.data.totals.unresolved + firm.data.totals.pending_approval
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { can, me } = useSession()
  const { hideSoon } = usePreferences()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const active = moduleOf(path)
  const { clientId } = useParams({ strict: false }) as { clientId?: string }
  const bankCount = useSidebarCount()

  const hrefFor = (entry: NavEntry): string => {
    if (entry.soon) return `/soon/${entry.id}`
    if (entry.id === 'settings') return `/${settingsHome(can)}`
    return moduleHref(entry.id, clientId)
  }

  const initials = (me?.full_name || me?.email || '?')
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="px-4 py-3.5 text-white">
        <Brand />
      </div>
      <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-4">
        {GROUPS.map((group) => {
          const items = group.items.filter((item) => {
            if (item.permission && !can(item.permission)) return false
            if (item.soon && hideSoon) return false
            return true
          })
          if (items.length === 0) return null
          return (
            <div key={group.label} className="pt-2.5">
              <div className="px-3 pb-1 text-xs font-medium text-sidebar-muted">{group.label}</div>
              <ul className="grid gap-0.5">
                {items.map((item) => {
                  const isActive = active === item.id
                  return (
                    <li key={item.id}>
                      <Link
                        to={hrefFor(item) as never}
                        onClick={onNavigate}
                        aria-current={isActive ? 'page' : undefined}
                        className={cn(
                          'relative flex h-9 items-center gap-2.5 rounded-md px-3 text-sm font-medium hover:bg-white/5 hover:text-white [&_svg]:size-4 [&_svg]:shrink-0',
                          item.soon ? 'text-sidebar-muted' : 'text-sidebar-foreground',
                          isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-bar',
                        )}
                      >
                        {item.icon}
                        <span className="truncate">{item.label}</span>
                        {item.soon ? (
                          <span className={chip}>Soon</span>
                        ) : item.id === 'bank' && bankCount ? (
                          <span className={cn(chip, 'num')} title={clientId ? 'Rows waiting for this client' : 'Rows waiting across the firm'}>
                            {bankCount}
                          </span>
                        ) : null}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })}
      </nav>
      <div className="flex items-center gap-2.5 border-t border-white/10 px-4 py-3 text-xs text-sidebar-muted">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-white/10 text-[13px] font-semibold text-sidebar-foreground" aria-hidden>
          {initials}
        </span>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-sidebar-foreground">{me?.full_name || me?.email}</div>
          <div className="truncate">{me?.role_display}</div>
        </div>
      </div>
    </div>
  )
}

function settingsHome(can: (permission: string) => boolean): string {
  return can('team.view') ? 'settings/team' : can('firm.manage') ? 'settings/firm' : 'settings/preferences'
}

/** Who's books these are. Opens the palette, which lists clients (and "All clients") as you type. */
function ClientPicker() {
  const { clientId } = useParams({ strict: false }) as { clientId?: string }
  const palette = usePalette()
  const client = useQuery({ ...clientDetail(clientId ?? ''), enabled: !!clientId })
  const label = clientId ? (client.data?.name ?? '…') : 'All clients'
  return (
    <Button
      variant="secondary"
      className="min-w-0 flex-1 justify-between gap-2 px-3 sm:flex-none sm:min-w-52 sm:max-w-72"
      onClick={() => palette.open()}
      aria-label={`Client: ${label}. Change client`}
      aria-haspopup="dialog"
    >
      <span className="flex min-w-0 items-center gap-2">
        <Building2 className="text-muted-foreground" aria-hidden />
        <span className="truncate">{label}</span>
      </span>
      <span className="flex shrink-0 items-center gap-1.5 text-muted-foreground">
        <span className="hidden items-center gap-1 xl:flex">
          <Kbd>Alt</Kbd>
          <Kbd>C</Kbd>
        </span>
        <ChevronsUpDown className="!size-3.5" aria-hidden />
      </span>
    </Button>
  )
}

/** Modules where the financial year in view means something. */
const FY_MODULES: ModuleId[] = ['dashboard', 'clients', 'pipeline', 'bookkeeping', 'bank', 'gst', 'reports']

/**
 * The financial year in view (April to March, named by the year it starts in). Inside a client it is
 * that client's remembered year, written to `?fy=`. Under All clients it is a firm-level year, also
 * carried in `?fy=`, and picking a client afterwards keeps it.
 */
function FySelect() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const { clientId, fy: clientFy, setFy: setClientFy, dataYears } = useFy()
  const search = useSearch({ strict: false }) as { fy?: unknown }
  const navigate = useNavigate()
  const module = moduleOf(path)
  if (!module || !FY_MODULES.includes(module)) return null

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
      className="h-9 shrink-0 rounded-md border border-input bg-card px-2.5 text-sm font-medium text-foreground"
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
      className="hidden h-9 min-w-0 max-w-sm flex-1 items-center gap-2 rounded-md border border-input bg-card px-3 text-sm text-faint hover:bg-hover lg:flex"
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

function UserMenu({ onShortcuts }: { onShortcuts: () => void }) {
  const { me, signOut } = useSession()
  const { theme, setTheme, density, setDensity, hideSoon, setHideSoon } = usePreferences()
  const initials = (me?.full_name || me?.email || '?')
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Account and preferences" className="rounded-full bg-secondary text-[13px] font-semibold">
          {initials}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <div className="px-2 py-2">
          <div className="truncate text-sm font-medium">{me?.full_name || me?.email}</div>
          <div className="truncate text-xs text-muted-foreground">{me?.email}</div>
          <div className="text-xs text-muted-foreground">{me?.role_display}</div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
          <DropdownMenuRadioItem value="light"><Sun /> Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark"><Moon /> Dark</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system"><Monitor /> Match my device</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuLabel>Rows</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={density} onValueChange={(v) => setDensity(v as Density)}>
          <DropdownMenuRadioItem value="comfortable"><Rows3 /> Comfortable</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="compact"><Rows3 /> Compact</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem checked={hideSoon} onCheckedChange={(v) => setHideSoon(v === true)}>
          <EyeOff /> Hide modules that are coming soon
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onShortcuts}>
          <Keyboard /> Keyboard shortcuts <Kbd className="ml-auto">?</Kbd>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void signOut()}>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** `g` then a letter jumps to a module. Plain keys are ignored while a field has focus (the registry's rule). */
function JumpKeys() {
  const { can } = useSession()
  const navigate = useNavigate()
  const { clientId } = useParams({ strict: false }) as { clientId?: string }
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

export function Shell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const navigate = useNavigate()
  const path = useRouterState({ select: (s) => s.location.pathname })

  useHotkey('?', 'Show keyboard shortcuts', () => setShortcutsOpen(true))
  const { can, me } = useSession()
  useClientPageTitle()
  useRouteFocus()
  useHotkey('g w', 'Go to staff performance', () => can('client.view') && void navigate({ to: '/staff' }), 'Go to')
  useHotkey('g t', 'Go to team & roles', () => can('team.view') && void navigate({ to: '/settings/team' }), 'Go to')
  useHotkey('g f', 'Go to firm settings', () => can('firm.manage') && void navigate({ to: '/settings/firm' }), 'Go to')

  // The drawer closes when the person navigates, and when the window grows past the breakpoint.
  useEffect(() => setMenuOpen(false), [path])
  useEffect(() => {
    const query = matchMedia('(min-width: 1024px)')
    const close = () => query.matches && setMenuOpen(false)
    query.addEventListener('change', close)
    return () => query.removeEventListener('change', close)
  }, [])

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

      <aside className="no-print sticky top-0 hidden h-svh w-[248px] shrink-0 lg:block">
        <Sidebar />
      </aside>

      <Drawer.Root open={menuOpen} onOpenChange={setMenuOpen}>
        <Drawer.Portal>
          <Drawer.Overlay className="fixed inset-0 z-40 bg-black/45 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms] lg:hidden" />
          <Drawer.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms] lg:hidden"
          >
            <Drawer.Title className="sr-only">Menu</Drawer.Title>
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineStrip />
        <header className="no-print sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background px-3 md:gap-3 lg:px-6">
          <Button variant="ghost" size="icon" className="size-11 shrink-0 lg:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          {me?.firm?.name && (
            <span className="hidden max-w-48 shrink-0 truncate border-r pr-3 text-[13px] font-medium text-muted-foreground xl:block">{me.firm.name}</span>
          )}
          <ClientPicker />
          <FySelect />
          <PaletteTrigger />
          <div className="ml-auto flex shrink-0 items-center gap-2 md:gap-3">
            <AssistantIndicator />
            <UserMenu onShortcuts={() => setShortcutsOpen(true)} />
          </div>
        </header>
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-[1400px] flex-1 p-4 outline-none md:p-6">
          <Outlet />
        </main>
      </div>

      <JumpKeys />
      <ShortcutSheet open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </div>
  )
}
