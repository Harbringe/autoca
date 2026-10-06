import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ModuleAlerts } from './AlertList'

const feed = {
  counts: { total: 2, by_module: {} },
  alerts: [
    { kind: 'k1', severity: 'medium', module: 'gst', client: 'c1', client_name: 'QA Alpha', title: 'Rows to review', detail: '5 rows wait', to: '/clients/c1/review', search: {}, amount_paise: null, count: 5 },
    { kind: 'k2', severity: 'critical', module: 'gst', client: 'c2', client_name: 'QA Beta', title: 'GST return overdue', detail: 'Due 20-09-2026', to: '/clients/c2/review', search: {}, amount_paise: null, count: 1 },
  ],
}

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { get: vi.fn(async () => feed) },
}))

async function setup() {
  const root = createRootRoute({ component: () => (<><ModuleAlerts module="gst" /><Outlet /></>) })
  const page = (path: string) => createRoute({ getParentRoute: () => root, path, component: () => <p>at {path}</p> })
  const router = createRouter({
    routeTree: root.addChildren([page('/'), page('/alerts'), page('/clients/$clientId/review')]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('the View alerts button on a module', () => {
  it('shows the count, lists every alert most serious first, and closes with the close button', async () => {
    const user = await setup()
    await user.click(await screen.findByRole('button', { name: /View alerts \(2\)/ }))
    const rows = await screen.findAllByRole('link', { name: /GST return overdue|Rows to review/ })
    expect(rows[0]).toHaveTextContent('GST return overdue')
    await user.click(screen.getByRole('button', { name: 'Close alerts' }))
    await waitFor(() => expect(screen.queryByText('Rows to review')).not.toBeInTheDocument())
  })
})
