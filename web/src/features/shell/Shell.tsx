import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useParams, useRouterState } from '@tanstack/react-router'
import { Building2, ChevronsUpDown, Keyboard, LogOut, Menu, Monitor, Moon, Rows3, Sun, UserCog, Users, Activity } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { clientDetail } from '@/api/queries/clients'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import { Kbd } from '@/components/ui/kbd'
import { Brand } from '@/features/auth/AuthLayout'
import { fyLabel, financialYearOf } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { usePreferences, type Density, type Theme } from '@/lib/preferences'
import { usePageTitle } from '@/lib/title'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { usePalette } from './CommandPalette'
import { ShortcutSheet } from './ShortcutSheet'
import { useFy } from './useFy'

interface NavItem {
  to: '/clients' | '/team' | '/work' | '/firm'
  label: string
  icon: ReactNode
  /** Shown only to people holding this permission. */
  permission?: string
}

const NAV: NavItem[] = [
  { to: '/clients', label: 'Clients', icon: <Users />, permission: 'client.view' },
  { to: '/work', label: 'Work', icon: <Activity />, permission: 'client.view' },
  { to: '/team', label: 'Team & roles', icon: <UserCog />, permission: 'team.view' },
  { to: '/firm', label: 'Firm settings', icon: <Building2 />, permission: 'firm.manage' },
]

const CLIENT_TAB_TITLE: Record<string, string> = {
  statements: 'Statements',
  review: 'Review',
  daybook: 'Day Book',
  reports: 'Reports',
  books: 'Books & sign-off',
  masters: 'Masters',
  team: 'Team & details',
}

/** The browser tab names the screen. Screens outside a client set their own title. */
function useClientPageTitle() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const parts = path.split('/').filter(Boolean)
  const title = parts[0] !== 'clients' ? undefined : parts.length === 1 ? 'Clients' : parts.length === 2 ? 'Overview' : (CLIENT_TAB_TITLE[parts[2]!] ?? undefined)
  usePageTitle(title)
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { can, me } = useSession()
  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="px-4 py-4 text-white">
        <Brand />
      </div>
      <nav aria-label="Main" className="grid gap-0.5 px-2">
        {NAV.filter((item) => !item.permission || can(item.permission)).map((item) => (
          <Link
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/85 hover:bg-sidebar-active hover:text-white data-[status=active]:bg-sidebar-active data-[status=active]:text-white [&_svg]:size-4"
            activeProps={{ 'data-status': 'active' }}
          >
            {item.icon}
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="mt-auto border-t border-white/10 px-4 py-3 text-xs text-sidebar-muted">
        <div className="truncate font-medium text-sidebar-foreground">{me?.firm?.name}</div>
        <div className="truncate">{me?.role_display}</div>
      </div>
    </div>
  )
}

function ClientSwitcher() {
  const { clientId } = useParams({ strict: false })
  const palette = usePalette()
  const client = useQuery({ ...clientDetail(clientId ?? ''), enabled: !!clientId })
  return (
    <Button
      variant="outline"
      className="min-w-0 flex-1 justify-between md:min-w-52 md:max-w-72 md:flex-none"
      onClick={() => palette.open()}
      aria-label="Switch client"
    >
      <span className="truncate">{clientId ? (client.data?.name ?? '…') : 'Select a client'}</span>
      <span className="flex shrink-0 items-center gap-1.5 text-muted-foreground">
        <span className="hidden items-center gap-1.5 md:flex">
          <Kbd>Alt</Kbd>
          <Kbd>C</Kbd>
        </span>
        <ChevronsUpDown className="!size-3.5" />
      </span>
    </Button>
  )
}

/** The financial year in view. April to March; the year is named by the year it starts in. */
function FySelect() {
  const { clientId, fy, setFy, dataYears } = useFy()
  // The year applies to one client's books, so it only shows inside a client.
  if (!clientId) return null
  const now = financialYearOf(new Date())
  // A year that has not begun has no books to show, so the list starts at the current one.
  const years = new Set([...Array.from({ length: 8 }, (_, i) => now - i), ...dataYears, fy])
  return (
    <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
      <span className="hidden sm:inline">Financial year</span>
      <select
        aria-label="Financial year"
        value={fy}
        onChange={(e) => setFy(Number(e.target.value))}
        className="h-9 rounded-md border border-input bg-card px-2.5 text-sm font-medium text-foreground"
      >
        {[...years]
          .sort((a, b) => b - a)
          .map((year) => (
            <option key={year} value={year}>
              FY {fyLabel(year)}
            </option>
          ))}
      </select>
    </label>
  )
}

function UserMenu({ onShortcuts }: { onShortcuts: () => void }) {
  const { me, signOut } = useSession()
  const { theme, setTheme, density, setDensity } = usePreferences()
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

export function Shell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const navigate = useNavigate()

  useHotkey('?', 'Show keyboard shortcuts', () => setShortcutsOpen(true))
  const { can } = useSession()
  useClientPageTitle()
  useHotkey('g c', 'Go to clients', () => void navigate({ to: '/clients' }), 'Go to')
  useHotkey('g w', 'Go to work', () => can('client.view') && void navigate({ to: '/work' }), 'Go to')
  useHotkey('g t', 'Go to team & roles', () => can('team.view') && void navigate({ to: '/team' }), 'Go to')
  useHotkey('g f', 'Go to firm settings', () => can('firm.manage') && void navigate({ to: '/firm' }), 'Go to')
  useHotkey('escape', 'Close a panel or dialog', () => setMenuOpen(false))

  return (
    <div className="flex min-h-svh">
      <aside className="no-print sticky top-0 hidden h-svh w-60 shrink-0 md:block">
        <Sidebar />
      </aside>

      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button className="absolute inset-0 bg-black/45" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-64">
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/90 px-3 backdrop-blur md:gap-3 md:px-4">
          <Button variant="ghost" size="icon" className="shrink-0 md:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          <ClientSwitcher />
          <div className="ml-auto flex shrink-0 items-center gap-2 md:gap-3">
            <FySelect />
            <UserMenu onShortcuts={() => setShortcutsOpen(true)} />
          </div>
        </header>
        <main className={cn('mx-auto w-full max-w-[1400px] flex-1 p-4 md:p-6')}>
          <Outlet />
        </main>
      </div>

      <ShortcutSheet open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </div>
  )
}
