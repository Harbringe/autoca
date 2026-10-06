import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider, useParams } from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { recordRecentClient, resetClientMemory, toggleClientPin } from '@/lib/recentClients'
import { ClientSwitcher } from './ClientSwitcher'
import { openClientSwitcher } from './switcherBus'

const CLIENTS = [
  { id: 'a', name: 'Divine Construwell Private Limited' },
  { id: 'b', name: 'Laxmi Synthetics' },
  { id: 'c', name: 'Sarika Gaggad' },
]

vi.mock('@/api/queries/clients', async () => {
  const { queryOptions } = await import('@tanstack/react-query')
  return {
    clientsList: (search: string) =>
      queryOptions({
        queryKey: ['t', 'list', search],
        queryFn: async () => {
          const results = CLIENTS.filter((c) => !search || c.name.toLowerCase().includes(search.toLowerCase()))
          return { count: results.length, next: null, previous: null, results }
        },
      }),
    clientDetail: (id: string) => queryOptions({ queryKey: ['t', 'one', id], queryFn: async () => CLIENTS.find((c) => c.id === id)! }),
  }
})

async function setup(start = '/clients/a/daybook') {
  const root = createRootRoute({
    component: () => (
      <>
        <ClientSwitcher currentId="a">
          <button type="button">Switch client</button>
        </ClientSwitcher>
        <Outlet />
      </>
    ),
  })
  const here = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/daybook', component: function Here() { return <p>at {(useParams({ strict: false }) as { clientId: string }).clientId} daybook</p> } })
  const profile = createRoute({ getParentRoute: () => root, path: '/clients/$clientId', component: () => <p>profile</p> })
  const list = createRoute({ getParentRoute: () => root, path: '/clients', component: () => <p>client list</p> })
  const router = createRouter({ routeTree: root.addChildren([here, profile, list]), history: createMemoryHistory({ initialEntries: [start] }) })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('the client switcher', () => {
  beforeEach(() => resetClientMemory())

  it('opens with the search box focused, pinned and recent clients, and a way to all of them', async () => {
    toggleClientPin('b')
    recordRecentClient('c')
    const user = await setup()
    await user.click(await screen.findByRole('button', { name: 'Switch client' }))
    const input = await screen.findByRole('combobox', { name: 'Search clients' })
    expect(input).toHaveFocus()
    expect(await screen.findByRole('option', { name: /Laxmi Synthetics/ })).toBeInTheDocument()
    expect(screen.getByText('Pinned')).toBeInTheDocument()
    expect(screen.getByText('Recent')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'All 3 clients' })).toHaveAttribute('href', '/clients')
  })

  it('narrows as you type and opens the pick with Enter, keeping the screen', async () => {
    const user = await setup()
    await user.click(await screen.findByRole('button', { name: 'Switch client' }))
    await user.type(await screen.findByRole('combobox', { name: 'Search clients' }), 'sar')
    const option = await screen.findByRole('option', { name: /Sarika Gaggad/ })
    expect(screen.queryByRole('option', { name: /Laxmi/ })).not.toBeInTheDocument()
    expect(option).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Enter}')
    expect(await screen.findByText('at c daybook')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('combobox')).not.toBeInTheDocument())
  })

  it('moves with the arrow keys', async () => {
    toggleClientPin('b')
    recordRecentClient('a')
    recordRecentClient('c')
    const user = await setup()
    await user.click(await screen.findByRole('button', { name: 'Switch client' }))
    await screen.findByRole('option', { name: /Laxmi Synthetics/ })
    await user.keyboard('{ArrowDown}{ArrowDown}')
    // Pinned Laxmi, then recent Sarika (the newest), then Divine.
    expect(screen.getByRole('option', { name: /Divine/ })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowUp}{Enter}')
    expect(await screen.findByText('at c daybook')).toBeInTheDocument()
  })

  it('says so when nothing matches, and does nothing on Enter', async () => {
    const user = await setup()
    await user.click(await screen.findByRole('button', { name: 'Switch client' }))
    await user.type(await screen.findByRole('combobox', { name: 'Search clients' }), 'zzz')
    expect(await screen.findByText(/No client matches/)).toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(screen.getByText('at a daybook')).toBeInTheDocument()
  })

  it('is what Alt+C opens while it is on screen', async () => {
    await setup()
    await screen.findByRole('button', { name: 'Switch client' })
    expect(openClientSwitcher()).toBe(true)
    expect(await screen.findByRole('combobox', { name: 'Search clients' })).toBeInTheDocument()
  })
})
