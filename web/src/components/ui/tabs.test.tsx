import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
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

// A long row keeps every tab in one row that scrolls sideways, with an arrow on each side that has more tabs beyond it.
async function renderLong(url: string) {
  const root = createRootRoute({ component: Outlet })
  const names = ['One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']
  const routes = names.map((name) =>
    createRoute({
      getParentRoute: () => root,
      path: `/${name.toLowerCase()}`,
      component: () => <TabNav label="Sections" items={names.map((n) => ({ to: `/${n.toLowerCase()}`, label: n, exact: true }))} />,
    }),
  )
  const router = createRouter({ routeTree: root.addChildren(routes), history: createMemoryHistory({ initialEntries: [url] }) })
  render(<RouterProvider router={router} />)
  return screen.findByRole('navigation', { name: 'Sections' })
}

function overflow(nav: HTMLElement, { scrollLeft, clientWidth, scrollWidth }: { scrollLeft: number; clientWidth: number; scrollWidth: number }) {
  Object.defineProperty(nav, 'clientWidth', { configurable: true, value: clientWidth })
  Object.defineProperty(nav, 'scrollWidth', { configurable: true, value: scrollWidth })
  nav.scrollLeft = scrollLeft
  fireEvent.scroll(nav)
}

describe('TabNav with more tabs than fit', () => {
  it('keeps every tab in the row and shows no arrows while they all fit', async () => {
    await renderLong('/one')
    expect(screen.getAllByRole('link')).toHaveLength(10)
    expect(screen.queryByRole('button', { name: /scroll sections/i })).not.toBeInTheDocument()
  })
  it('shows a right arrow when tabs run past the edge, and a left one once scrolled', async () => {
    const nav = await renderLong('/one')
    overflow(nav, { scrollLeft: 0, clientWidth: 300, scrollWidth: 900 })
    expect(await screen.findByRole('button', { name: 'Scroll Sections right' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Scroll Sections left' })).not.toBeInTheDocument()
    overflow(nav, { scrollLeft: 600, clientWidth: 300, scrollWidth: 900 })
    expect(await screen.findByRole('button', { name: 'Scroll Sections left' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Scroll Sections right' })).not.toBeInTheDocument()
  })
  it('moves the row when an arrow is pressed', async () => {
    const nav = await renderLong('/one')
    const scrollBy = vi.fn()
    nav.scrollBy = scrollBy
    overflow(nav, { scrollLeft: 0, clientWidth: 300, scrollWidth: 900 })
    await userEvent.click(await screen.findByRole('button', { name: 'Scroll Sections right' }))
    expect(scrollBy).toHaveBeenCalledWith(expect.objectContaining({ left: expect.any(Number) }))
    expect(scrollBy.mock.calls[0]?.[0].left).toBeGreaterThan(0)
  })
})
