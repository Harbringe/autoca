import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AlertBell } from './AlertBell'

const feed = {
  counts: { total: 2, by_module: {} },
  alerts: [
    { kind: 'k1', severity: 'medium', module: 'bank', client: 'c1', client_name: 'QA Alpha', title: 'Rows to review', detail: '5 rows wait', to: '/clients/c1/review', search: {}, amount_paise: null, count: 5 },
    { kind: 'k2', severity: 'critical', module: 'gst', client: 'c2', client_name: 'QA Beta', title: 'GST return overdue', detail: 'Due 20-09-2026', to: '/clients/c2/gst', search: {}, amount_paise: null, count: 1 },
  ],
}

vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { get: vi.fn(async () => feed) },
}))

async function setup() {
  const root = createRootRoute({ component: () => (<><AlertBell /><Outlet /></>) })
  const page = (path: string) => createRoute({ getParentRoute: () => root, path, component: () => <p>at {path}</p> })
  const router = createRouter({
    routeTree: root.addChildren([page('/'), page('/alerts'), page('/clients/$clientId/gst'), page('/clients/$clientId/review')]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('the alert bell', () => {
  it('shows the count, opens a panel with the most serious first, and navigates and closes on click', async () => {
    const user = await setup()
    const bell = await screen.findByRole('button', { name: 'Alerts: 2 need attention' })
    expect(bell).toHaveAttribute('aria-haspopup', 'dialog')
    await user.click(bell)
    const rows = await screen.findAllByRole('link', { name: /GST return overdue|Rows to review/ })
    expect(rows[0]).toHaveTextContent('GST return overdue')
    expect(rows[0]).toHaveTextContent('Urgent')
    expect(screen.getByRole('link', { name: 'View all alerts' })).toBeInTheDocument()
    await user.click(rows[0]!)
    expect(await screen.findByText('at /clients/$clientId/gst')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('link', { name: 'View all alerts' })).not.toBeInTheDocument())
  })
  it('narrows by severity and closes on Escape, returning focus to the bell', async () => {
    const user = await setup()
    const bell = await screen.findByRole('button', { name: 'Alerts: 2 need attention' })
    await user.click(bell)
    await user.click(await screen.findByRole('button', { name: /^To do/ }))
    expect(screen.queryByText('GST return overdue')).not.toBeInTheDocument()
    expect(screen.getByText('Rows to review')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByText('Rows to review')).not.toBeInTheDocument())
    expect(bell).toHaveFocus()
  })
})
