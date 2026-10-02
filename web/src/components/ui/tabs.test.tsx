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
