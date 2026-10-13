import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ContextBar } from './Crumbs'

vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('./clientHeader', () => ({ useClientHeader: () => ({ name: 'Laxmi', line: 'FY 2026-27' }) }))
vi.mock('./ClientSwitcher', () => ({ ClientSwitcher: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('./FySelect', () => ({ FySelect: () => <button type="button">FY 2026-27</button> }))

function renderAt(path: string, clientId?: string) {
  const root = createRootRoute()
  const everything = createRoute({ getParentRoute: () => root, path: '$', component: () => <ContextBar clientId={clientId} firmName="Rudra's Firm" /> })
  const router = createRouter({ routeTree: root.addChildren([everything]), history: createMemoryHistory({ initialEntries: [path] }) })
  render(<RouterProvider router={router} />)
  return router
}

describe('the context bar', () => {
  it('shows the whole path to where you are, down to the section', async () => {
    renderAt('/clients/c1/review', 'c1')
    const nav = await screen.findByRole('navigation', { name: 'Where you are' })
    const steps = within(nav).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent)
    expect(steps).toEqual(['Client: Laxmi. Switch client', 'FY 2026-27', 'Place: Bank statements. Change', 'Bank statements section: Review. Change'])
    expect(within(nav).getByRole('link', { name: "Rudra's Firm" })).toBeInTheDocument()
    // the last step is the page itself
    expect(within(nav).getByRole('button', { name: /section: Review/ })).toHaveAttribute('aria-current', 'page')
  })

  it('stops at the place for a place with no sections', async () => {
    renderAt('/clients/c1/documents', 'c1')
    const nav = await screen.findByRole('navigation', { name: 'Where you are' })
    expect(within(nav).getByRole('button', { name: /^Place: Documents/ })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).queryByRole('button', { name: /section/ })).toBeNull()
  })

  it('opens a step from the keyboard, lists its neighbours with their keys, and goes to the one chosen', async () => {
    const user = userEvent.setup()
    const router = renderAt('/clients/c1/review', 'c1')
    const place = await screen.findByRole('button', { name: /^Place: Bank statements/ })
    place.focus()
    await user.keyboard('{Enter}')
    const items = await screen.findAllByRole('menuitem')
    // each entry says the key that opens it (the letters are shown capitalised)
    const said = items.map((i) => i.textContent)
    expect(said).toContain('Bank statementsgs')
    expect(said).toContain('Overviewgo')
    expect(said).toContain('Pipeline')
    await user.keyboard('{Home}{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe('/clients/c1'))
  })

  it('offers the sections of the place and goes to the one chosen', async () => {
    const user = userEvent.setup()
    const router = renderAt('/clients/c1/review', 'c1')
    const section = await screen.findByRole('button', { name: /section: Review/ })
    section.focus()
    await user.keyboard('{Enter}')
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual(['Statementsgs', 'Reviewgv'])
    await user.keyboard('{Home}{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe('/clients/c1/statements'))
  })

  it('under All clients names the page instead of a client', async () => {
    renderAt('/clients')
    const nav = await screen.findByRole('navigation', { name: 'Where you are' })
    expect(within(nav).getByText('All clients').closest('[aria-current]')).toHaveAttribute('aria-current', 'page')
  })
})
