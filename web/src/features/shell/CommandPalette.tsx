// Ctrl+K: go anywhere, do anything, without leaving the keyboard.
//
// One list, three kinds of thing: clients to jump to (searched on the server as you type,
// so a firm with hundreds of clients is as quick as one with five), screens to go to, and
// actions. Typing narrows all three; the first match is selected, so Enter runs it.

import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useRouterState, useSearch } from '@tanstack/react-router'
import { Command } from 'cmdk'
import { Activity, BarChart3, BookOpen, FileSpreadsheet, Landmark, Building2, FileText, ListChecks, Moon, PanelTop, Scale, Sun, Upload, UserCog, Users } from 'lucide-react'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { clientsList } from '@/api/queries/clients'
import { Kbd } from '@/components/ui/kbd'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { parseFy } from '@/lib/fy'
import { useHotkey } from '@/lib/hotkeys'
import { moduleHref } from '@/lib/jump'
import { switchClientPath } from '@/lib/modules'
import { usePreferences } from '@/lib/preferences'
import { useSession } from '@/session/session'

interface PaletteApi {
  open: (initialSearch?: string) => void
}
const Ctx = createContext<PaletteApi | null>(null)

export function usePalette(): PaletteApi {
  const value = useContext(Ctx)
  if (!value) throw new Error('usePalette outside PaletteProvider')
  return value
}

function useDebounced<T>(value: T, ms = 200): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

export function PaletteProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const api = useMemo<PaletteApi>(
    () => ({
      open: (initial = '') => {
        setSearch(initial)
        setOpen(true)
      },
    }),
    [],
  )

  useHotkey('ctrl+k', 'Search clients, go to a screen, run an action', () => api.open())
  useHotkey('alt+c', 'Switch client', () => api.open())

  return (
    <Ctx.Provider value={api}>
      {children}
      <Dialog open={isOpen} onOpenChange={setOpen}>
        <DialogContent className="top-[20%] max-w-xl translate-y-0 gap-0 overflow-hidden p-0" aria-describedby={undefined}>
          <DialogTitle className="sr-only">Command palette</DialogTitle>
          <DialogDescription className="sr-only">Search for a client, a screen or an action.</DialogDescription>
          <PaletteBody search={search} setSearch={setSearch} close={() => setOpen(false)} />
        </DialogContent>
      </Dialog>
    </Ctx.Provider>
  )
}

interface Item {
  value: string
  label: string
  group: 'This client' | 'Go to' | 'Preferences' | 'Account'
  icon?: ReactNode
  run: () => void
}

const CLIENTS_SHOWN = 8

function PaletteBody({ search, setSearch, close }: { search: string; setSearch: (s: string) => void; close: () => void }) {
  const navigate = useNavigate()
  const { can, signOut } = useSession()
  const { theme, setTheme, density, setDensity } = usePreferences()
  const term = useDebounced(search.trim())
  const { clientId } = useParams({ strict: false })
  const path = useRouterState({ select: (s) => s.location.pathname })
  const fromUrl = parseFy((useSearch({ strict: false }) as { fy?: unknown }).fy)
  const [selected, setSelected] = useState('')

  const clients = useQuery({ ...clientsList(term), enabled: can('client.view') })

  const commands = useMemo<Item[]>(() => {
    const go = (action: () => void) => () => {
      close()
      action()
    }
    const here = clientId
      ? ([
          { value: 'c-upload', label: 'Upload bank statement', group: 'This client', icon: <Upload />, run: go(() => void navigate({ to: '/clients/$clientId/statements', params: { clientId } }).then(() => setTimeout(() => document.dispatchEvent(new CustomEvent('autoca:upload')), 50))) },
          { value: 'c-review', label: 'Review transactions', group: 'This client', icon: <ListChecks />, run: go(() => void navigate({ to: '/clients/$clientId/review', params: { clientId }, search: { stage: 'unresolved' } })) },
          { value: 'c-bills', label: 'Purchases & Sales', group: 'This client', icon: <FileText />, run: go(() => void navigate({ to: '/clients/$clientId/bills', params: { clientId } })) },
          { value: 'c-daybook', label: 'Day Book', group: 'This client', icon: <BookOpen />, run: go(() => void navigate({ to: '/clients/$clientId/daybook', params: { clientId } })) },
          { value: 'c-bookkeeping', label: 'Books overview', group: 'This client', icon: <BookOpen />, run: go(() => void navigate({ to: '/clients/$clientId/bookkeeping', params: { clientId } })) },
          { value: 'c-tb', label: 'Trial Balance', group: 'This client', icon: <Scale />, run: go(() => void navigate({ to: '/clients/$clientId/reports', params: { clientId }, search: { report: 'tb' } })) },
          { value: 'c-pl', label: 'Profit & Loss A/c', group: 'This client', icon: <FileText />, run: go(() => void navigate({ to: '/clients/$clientId/reports', params: { clientId }, search: { report: 'pl' } })) },
          { value: 'c-bs', label: 'Balance Sheet', group: 'This client', icon: <FileText />, run: go(() => void navigate({ to: '/clients/$clientId/reports', params: { clientId }, search: { report: 'bs' } })) },
          { value: 'c-books', label: 'Books & sign-off', group: 'This client', icon: <ListChecks />, run: go(() => void navigate({ to: '/clients/$clientId/books', params: { clientId } })) },
          ...(can('team.view') || can('client.update')
            ? ([{ value: 'c-team', label: 'Settings & team', group: 'This client', icon: <Users />, run: go(() => void navigate({ to: '/clients/$clientId/team', params: { clientId } })) }] satisfies Item[])
            : []),
          { value: 'c-ledgers', label: 'Ledgers (chart of accounts)', group: 'This client', icon: <BookOpen />, run: go(() => void navigate({ to: '/clients/$clientId/ledgers', params: { clientId } })) },
        ] satisfies Item[])
      : []
    return [
      ...here,
      ...(can('client.view')
        ? ([{ value: 'go-dashboard', label: 'Dashboard', group: 'Go to', icon: <PanelTop />, run: go(() => void navigate({ to: '/dashboard' })) }] satisfies Item[])
        : []),
      { value: 'go-clients', label: 'Clients', group: 'Go to', icon: <Users />, run: go(() => void navigate({ to: '/clients' })) },
      ...(can('client.view')
        ? ([{ value: 'go-pipeline', label: 'Work pipeline', group: 'Go to', icon: <Activity />, run: go(() => void navigate({ to: '/pipeline' })) }] satisfies Item[])
        : []),
      ...(can('report.view')
        ? ([{ value: 'go-bookkeeping', label: 'Bookkeeping', group: 'Go to', icon: <BookOpen />, run: go(() => void navigate({ to: (clientId ? `/clients/${clientId}/bookkeeping` : '/bookkeeping') as never })) }] satisfies Item[])
        : []),
      ...(can('transaction.view')
        ? ([{ value: 'go-bank', label: 'Bank statements', group: 'Go to', icon: <Landmark />, run: go(() => void navigate({ to: (clientId ? `/clients/${clientId}/statements` : '/bank') as never })) }] satisfies Item[])
        : []),
      ...(can('report.view')
        ? ([{ value: 'go-reports', label: 'Reports', group: 'Go to', icon: <BarChart3 />, run: go(() => void navigate({ to: (clientId ? `/clients/${clientId}/reports` : '/reports') as never })) }] satisfies Item[])
        : []),
      ...(can('gst.view')
        ? ([{ value: 'go-gst', label: 'GST reconciliation', group: 'Go to', icon: <FileSpreadsheet />, run: go(() => void navigate({ to: moduleHref('gst', clientId) as never })) }] satisfies Item[])
        : []),
      ...(can('client.view')
        ? ([{ value: 'go-work', label: can('team.view') ? 'Staff performance' : 'My work', group: 'Go to', icon: <Activity />, run: go(() => void navigate({ to: '/staff' })) }] satisfies Item[])
        : []),
      ...(can('team.view')
        ? ([{ value: 'go-team', label: 'Team & roles', group: 'Go to', icon: <UserCog />, run: go(() => void navigate({ to: '/settings/team' })) }] satisfies Item[])
        : []),
      ...(can('firm.manage')
        ? ([{ value: 'go-firm', label: 'Firm settings', group: 'Go to', icon: <Building2 />, run: go(() => void navigate({ to: '/settings/firm' })) }] satisfies Item[])
        : []),
      {
        value: 'toggle-theme',
        label: theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme',
        group: 'Preferences',
        icon: theme === 'dark' ? <Sun /> : <Moon />,
        run: go(() => setTheme(theme === 'dark' ? 'light' : 'dark')),
      },
      {
        value: 'toggle-density',
        label: density === 'compact' ? 'Use comfortable rows' : 'Use compact rows',
        group: 'Preferences',
        icon: <PanelTop />,
        run: go(() => setDensity(density === 'compact' ? 'comfortable' : 'compact')),
      },
      { value: 'sign-out', label: 'Sign out', group: 'Account', run: go(() => void signOut()) },
    ]
  }, [close, navigate, theme, setTheme, density, setDensity, signOut, clientId, can])

  // Commands narrow by what is typed (the search box is live; the client list follows after a pause).
  const typed = search.trim().toLowerCase()
  const matching = commands.filter((c) => !typed || c.label.toLowerCase().includes(typed))
  // Client results are for the text as it was a moment ago. Until they catch up they are not
  // shown, so Enter can never open a client the person has already typed past.
  // `isPlaceholderData` is the previous search's rows kept on screen while the new ones load.
  const settled = term === search.trim() && !clients.isPlaceholderData
  const clientRows = settled ? (clients.data?.results.slice(0, CLIENTS_SHOWN) ?? []) : []
  const moreClients = settled ? Math.max(0, (clients.data?.count ?? 0) - CLIENTS_SHOWN) : 0

  // The first thing listed is selected, so Enter always does something sensible.
  const allClientsShown = !typed || 'all clients'.includes(typed)
  const firstValue = allClientsShown ? 'client-all' : clientRows[0] ? `client-${clientRows[0].id}` : matching[0]?.value
  useEffect(() => setSelected(firstValue ?? ''), [firstValue, typed])

  const nothing = clientRows.length === 0 && matching.length === 0 && !allClientsShown

  return (
    <Command shouldFilter={false} label="Command palette" loop value={selected} onValueChange={setSelected}>
      <Command.Input
        value={search}
        onValueChange={setSearch}
        placeholder="Search clients or type a command…"
        className="h-12 w-full border-b bg-transparent px-4 text-sm outline-none placeholder:text-faint"
      />
      <Command.List className="max-h-80 overflow-y-auto p-1.5">
        {nothing && (
          <div className="p-6 text-center text-sm text-muted-foreground" role="status">
            {clients.isFetching || !settled ? 'Searching…' : `Nothing matches “${search.trim()}”.`}
          </div>
        )}

        {(clientRows.length > 0 || allClientsShown) && (
          <Group heading="Clients">
            {allClientsShown && (
              <Row
                value="client-all"
                icon={<Users />}
                onSelect={() => {
                  close()
                  void navigate({ to: switchClientPath(path, null) as never })
                }}
              >
                All clients
              </Row>
            )}
            {clientRows.map((client) => (
              <Row
                key={client.id}
                value={`client-${client.id}`}
                icon={<Building2 />}
                onSelect={() => {
                  close()
                  // The module and tab stay; a year chosen under All clients comes along.
                  void navigate({ to: switchClientPath(path, client.id) as never, search: (!clientId && fromUrl ? { fy: fromUrl } : undefined) as never })
                }}
              >
                {client.name}
                {client.id === clientId && <span className="ml-auto text-xs text-muted-foreground">Current</span>}
              </Row>
            ))}
            {moreClients > 0 && (
              <div className="px-2.5 py-1.5 text-xs text-muted-foreground">
                and {moreClients} more — type more of the name to narrow it down
              </div>
            )}
          </Group>
        )}

        {(['This client', 'Go to', 'Preferences', 'Account'] as const).map((group) => {
          const rows = matching.filter((c) => c.group === group)
          return rows.length > 0 ? (
            <Group key={group} heading={group}>
              {rows.map((item) => (
                <Row key={item.value} value={item.value} icon={item.icon} onSelect={item.run}>
                  {item.label}
                </Row>
              ))}
            </Group>
          ) : null
        })}
      </Command.List>
      <div className="flex items-center gap-4 border-t px-4 py-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><Kbd>Enter</Kbd> select</span>
        <span className="flex items-center gap-1.5"><Kbd>Esc</Kbd> close</span>
      </div>
    </Command>
  )
}

function Group({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground"
    >
      {children}
    </Command.Group>
  )
}

function Row({ icon, children, ...props }: { value: string; icon?: ReactNode; onSelect: () => void; children: ReactNode }) {
  return (
    <Command.Item
      {...props}
      className="flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-sm data-[selected=true]:bg-hover [&_svg]:size-4 [&_svg]:text-muted-foreground"
    >
      {icon}
      {children}
    </Command.Item>
  )
}
