import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { TabNav } from './tabs'

// Tabs that share one path and differ only by ?report= must not all look current, and choosing one
// must keep the rest of the search (?fy=).
async function renderAt(url: string) {
  const root = createRootRoute({ component: Outlet })
  const reports = createRoute({
    getParentRoute: () => root,
    path: '/reports',
    validateSearch: (s: Record<string, unknown>) => ({
      report: s.report === 'pl' ? 'pl' : 'tb',
      fy: typeof s.fy === 'number' ? s.fy : undefined,
    }),
    component: () => (
      <TabNav
        label="Reports"
        items={[
          { to: '/reports', label: 'Trial Balance', search: { report: 'tb' } },
          { to: '/reports', label: 'Profit & Loss', search: { report: 'pl' } },
        ]}
      />
    ),
  })
  const router = createRouter({ routeTree: root.addChildren([reports]), history: createMemoryHistory({ initialEntries: [url] }) })
  render(<RouterProvider router={router} />)
  await screen.findByRole('navigation', { name: 'Reports' })
}

describe('TabNav with search tabs', () => {
  it('marks only the tab whose search matches', async () => {
    await renderAt('/reports?report=pl')
    expect(screen.getByRole('link', { name: 'Profit & Loss' }).getAttribute('data-status')).toBe('active')
    expect(screen.getByRole('link', { name: 'Trial Balance' }).getAttribute('data-status')).not.toBe('active')
  })
  it('treats a missing report as the default tab and keeps ?fy= in every link', async () => {
    await renderAt('/reports?fy=2024')
    expect(screen.getByRole('link', { name: 'Trial Balance' }).getAttribute('data-status')).toBe('active')
    expect(screen.getByRole('link', { name: 'Profit & Loss' }).getAttribute('href')).toContain('fy=2024')
  })
})

// A long row keeps seven in the row and folds the rest under "More", which names the current one when you are on it.
async function renderLong(url: string) {
  const root = createRootRoute({ component: Outlet })
  const names = ['One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']
  const routes = names.map((name) =>
    createRoute({
      getParentRoute: () => root,
      path: `/${name.toLowerCase()}`,
      component: () => (
        <TabNav label="Sections" maxVisible={7} items={names.map((n) => ({ to: `/${n.toLowerCase()}`, label: n, exact: true }))} />
      ),
    }),
  )
  const router = createRouter({ routeTree: root.addChildren(routes), history: createMemoryHistory({ initialEntries: [url] }) })
  render(<RouterProvider router={router} />)
  await screen.findByRole('navigation', { name: 'Sections' })
}

describe('TabNav with more tabs than fit', () => {
  it('shows seven and puts the rest under More', async () => {
    await renderLong('/one')
    expect(screen.getAllByRole('link')).toHaveLength(7)
    expect(screen.getByRole('button', { name: 'More' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Ten' })).not.toBeInTheDocument()
  })
  it('names the current tab on the More button when it is one of the folded ones', async () => {
    await renderLong('/nine')
    expect(screen.getByRole('button', { name: 'Nine' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'More' })).not.toBeInTheDocument()
  })
})
