import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { PreferencesProvider } from '@/lib/preferences'
import { recordRecentClient, resetClientMemory } from '@/lib/recentClients'
import { ClientNavList } from './ClientPanel'
import { ClientStrip } from './PhoneChrome'
import { Rail } from './Rail'

let held = new Set<string>()
vi.mock('@/session/session', () => ({
  useSession: () => ({ can: (p: string) => held.has(p), me: { full_name: 'Owner', email: 'o@example.test', role_display: 'Firm owner' }, signOut: vi.fn() }),
}))
vi.mock('@/api/queries/clients', async () => {
  const { queryOptions } = await import('@tanstack/react-query')
  const names: Record<string, string> = { a: 'Divine Construwell Private Limited', b: 'Laxmi Synthetics', c: 'Sarika Gaggad' }
  return {
    V1: '/api/v1',
    clientKeys: { part: (id: string, ...rest: string[]) => ['t', 'part', id, ...rest] },
    reviewSummary: (id: string) => queryOptions({ queryKey: ['t', 'review', id], queryFn: async () => ({ total: 12 }) }),
    clientDetail: (id: string) =>
      queryOptions({
        queryKey: ['t', 'one', id],
        queryFn: async () => {
          if (!names[id]) throw new Error('gone')
          return { id, name: names[id] }
        },
      }),
  }
})
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { get: vi.fn(async () => ({ counts: { total: 9, by_module: {} }, alerts: [] })) },
}))

const ALL = ['client.view', 'document.view', 'transaction.view', 'journal.view', 'report.view', 'gst.view', 'team.view', 'client.update']

async function inRouter(path: string, ui: ReactNode) {
  const root = createRootRoute({ component: () => (<>{ui}<Outlet /></>) })
  const any = createRoute({ getParentRoute: () => root, path: '$', component: () => null })
  const router = createRouter({ routeTree: root.addChildren([any]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PreferencesProvider>
        <RouterProvider router={router} />
      </PreferencesProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  held = new Set(ALL)
  resetClientMemory()
})

describe('the client panel', () => {
  it('lists the places, lights the one the address is in, and counts review rows on Bank statements', async () => {
    await inRouter('/clients/a/daybook', <ClientNavList clientId="a" />)
    const nav = await screen.findByRole('navigation', { name: 'Client screens' })
    await screen.findByText('12')
    const links = within(nav).getAllByRole('link')
    expect(links.map((l) => l.textContent?.replace(/ rows waiting$/, ''))).toEqual([
      'Overview', 'Pipeline', 'Bank statements12', 'Documents', 'Bookkeeping', 'GST', 'Reports', 'Client settings',
    ])
    const current = links.filter((l) => l.getAttribute('aria-current') === 'page')
    expect(current).toHaveLength(1)
    expect(current[0]).toHaveTextContent('Bookkeeping')
    expect(screen.getByRole('link', { name: 'Bookkeeping' })).toHaveAttribute('href', '/clients/a/bookkeeping')
  })

  it('hides what the person may not open', async () => {
    held = new Set(['client.view', 'transaction.view'])
    await inRouter('/clients/a', <ClientNavList clientId="a" />)
    const nav = await screen.findByRole('navigation', { name: 'Client screens' })
    await screen.findByText('12')
    expect(within(nav).getAllByRole('link').map((l) => l.textContent?.replace(/ rows waiting$/, ''))).toEqual(['Overview', 'Pipeline', 'Bank statements12'])
  })
})

describe('the phone strip', () => {
  it('is there inside a client with the five screens, 44px tall, and marks the current one', async () => {
    await inRouter('/clients/a/review', <ClientStrip clientId="a" />)
    const strip = await screen.findByRole('navigation', { name: 'Client screens' })
    await screen.findByText('12')
    const links = within(strip).getAllByRole('link')
    expect(links.map((l) => l.textContent?.replace(/ rows waiting$/, ''))).toEqual(['Overview', 'Bank12', 'Documents', 'Books', 'GST', 'Reports'])
    expect(links.every((l) => l.className.includes('h-11'))).toBe(true)
    expect(links.filter((l) => l.getAttribute('aria-current') === 'page').map((l) => l.textContent)).toEqual([expect.stringContaining('Bank')])
  })
})

describe('the rail', () => {
  it('names every place under its icon, shows the firm count in the firm only, and recent clients as discs', async () => {
    recordRecentClient('c')
    recordRecentClient('b')
    recordRecentClient('gone')
    recordRecentClient('a')
    await inRouter('/clients/a/daybook', <Rail onShortcuts={() => {}} />)
    const main = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(main).getAllByRole('link').map((l) => l.textContent)).toEqual(['Home', 'Clients', 'Alerts', 'Staff', 'Settings'])
    // Inside a client the rail carries no firm count: the bell speaks for the client.
    expect(within(main).getByRole('link', { name: 'Alerts' })).toBeInTheDocument()
    const recent = await screen.findByRole('region', { name: 'Recent clients' })
    const discs = await within(recent).findAllByRole('link')
    expect(discs.map((d) => d.getAttribute('aria-label'))).toEqual(['Divine Construwell Private Limited', 'Laxmi Synthetics', 'Sarika Gaggad'])
    expect(discs[0]).toHaveAttribute('aria-current', 'page')
    expect(discs[0]).toHaveTextContent('DC')
    expect(discs[1]).not.toHaveAttribute('aria-current')
  })

  it('carries no alert count on a firm page, and lights the place', async () => {
    await inRouter('/clients', <Rail onShortcuts={() => {}} />)
    expect(await screen.findByRole('link', { name: 'Alerts' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^Alerts\s*\d/ })).toBeNull()
    expect(screen.getByRole('link', { name: 'Clients' })).toHaveAttribute('aria-current', 'page')
  })
})
