import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FigureDialog } from './FirmFigures'
import { FirmScreen } from './FirmScreen'

const FIRM = {
  id: 'f1',
  name: 'Plant Firm',
  created_at: '2026-10-04T10:00:00Z',
  owner: { id: 'm0', name: 'Owner One', is_owner: true },
  admins: [{ id: 'm0', name: 'Owner One', is_owner: true }],
  counts: { active_members: 13, senior_cas: 2, staff: 10, clients: 3 },
  can: { rename: true, transfer: true },
}
const person = (n: number, role: string) => ({ id: `m${n}`, name: `Person ${n}`, email: `p${n}@x.test`, role, role_display: role === 'STAFF' ? 'Staff' : 'Senior CA', is_owner: false, is_active: true, last_login: null })
const MEMBERS = [...Array.from({ length: 11 }, (_, i) => person(i + 1, 'STAFF')), person(12, 'SENIOR_CA'), { ...person(13, 'STAFF'), is_active: false }]
const rename = vi.fn()

vi.mock('@/api/queries/team', async () => {
  const { queryOptions } = await import('@tanstack/react-query')
  return {
    firmSettings: () => queryOptions({ queryKey: ['firm'], queryFn: async () => FIRM }),
    teamMembers: () => queryOptions({ queryKey: ['members'], queryFn: async () => ({ results: MEMBERS }) }),
    teamClients: () =>
      queryOptions({ queryKey: ['tc'], queryFn: async () => ({ results: [{ id: 'c1', name: 'Laxmi', lead: null, unresolved: 3, pending_approval: 0, books_to_send: false, team: [] }] }) }),
    useRenameFirm: () => ({ mutateAsync: rename, isPending: false }),
    useTransferOwner: () => ({ mutateAsync: vi.fn() }),
  }
})
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true, refresh: vi.fn() }) }))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute()
  const page = createRoute({ getParentRoute: () => root, path: '/', component: () => <>{ui}</> })
  const other = createRoute({ getParentRoute: () => root, path: '/$x/$y', component: () => <p>elsewhere</p> })
  const router = createRouter({ routeTree: root.addChildren([page, other]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('the firm settings sheet', () => {
  it('follows what is typed in the preview, and offers Save and Discard only once something changed', async () => {
    const user = userEvent.setup()
    wrap(<FirmScreen />)
    const input = await screen.findByLabelText('Name on the books')
    expect(screen.queryByRole('region', { name: 'Unsaved changes' })).toBeNull()
    await user.clear(input)
    await user.type(input, 'Kulkarni')
    expect(within(screen.getByRole('complementary', { name: 'Preview' })).getAllByText('Kulkarni').length).toBeGreaterThan(0)
    const bar = screen.getByRole('region', { name: 'Unsaved changes' })
    await user.click(within(bar).getByRole('button', { name: 'Discard' }))
    expect(input).toHaveValue('Plant Firm')
    expect(screen.queryByRole('region', { name: 'Unsaved changes' })).toBeNull()
    expect(rename).not.toHaveBeenCalled()
  })

  it('saves only when the bar says so', async () => {
    const user = userEvent.setup()
    wrap(<FirmScreen />)
    const input = await screen.findByLabelText('Name on the books')
    await user.clear(input)
    await user.type(input, 'Kulkarni')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(rename).toHaveBeenCalledWith('Kulkarni'))
  })

  it('opens the list behind a figure from the preview', async () => {
    const user = userEvent.setup()
    wrap(<FirmScreen />)
    await user.click(await screen.findByRole('button', { name: /Clients 3/ }))
    expect(await screen.findByRole('dialog', { name: 'Clients' })).toBeInTheDocument()
    expect(await screen.findByText('Laxmi')).toBeInTheDocument()
  })
})

describe('the lists behind the figures', () => {
  it('pages the people, active ones only, 10 to a page', async () => {
    wrap(<FigureDialog figure="people" onClose={() => {}} />)
    await screen.findByText('Showing 1–10 of 12')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Showing 11–12 of 12')
  })

  it('keeps Senior CAs and staff apart', async () => {
    wrap(<FigureDialog figure="senior" onClose={() => {}} />)
    expect(await screen.findByText('Person 12')).toBeInTheDocument()
    expect(screen.queryByText('Person 1')).toBeNull()
  })
})
