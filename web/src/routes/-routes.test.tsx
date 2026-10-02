import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

// The real route tree, with the session signed in and the shell reduced to a marker plus its Outlet,
// so the question under test is only "where does the router draw an unknown address?".
vi.mock('@/session/session', () => ({
  useSession: () => ({ state: { kind: 'ready' }, me: { permissions: [] }, can: () => false }),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}))
vi.mock('@/features/shell/Shell', () => ({
  Shell: () => (
    <div>
      <div data-testid="shell">Shell</div>
      <Outlet />
    </div>
  ),
}))

async function renderAt(url: string) {
  const { routeTree } = await import('@/routeTree.gen')
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [url] }) })
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe('unknown addresses', () => {
  it('draw the not-found page inside the shell', async () => {
    await renderAt('/nope-404')
    expect(await screen.findByRole('heading', { name: 'This page does not exist' })).toBeInTheDocument()
    expect(screen.getByTestId('shell')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to Clients' })).toBeInTheDocument()
  })
  it('does the same one level down, under a client', async () => {
    await renderAt('/clients/abc/not-a-tab')
    expect(await screen.findByRole('heading', { name: 'This page does not exist' })).toBeInTheDocument()
    expect(screen.getByTestId('shell')).toBeInTheDocument()
  })
})

describe('redirects keep the financial year', () => {
  it('sends / to the dashboard with ?fy=', async () => {
    const router = await renderAt('/?fy=2025')
    await vi.waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
    expect(router.state.location.search).toMatchObject({ fy: 2025 })
  })
  it('sends / without a year to the dashboard without one', async () => {
    const router = await renderAt('/')
    await vi.waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
    expect(router.state.location.search).not.toHaveProperty('fy', 2025)
  })
  it('sends the old GST coming-soon address to the GST screen', async () => {
    const router = await renderAt('/soon/gst')
    await vi.waitFor(() => expect(router.state.location.pathname).toBe('/gst'))
  })
})
