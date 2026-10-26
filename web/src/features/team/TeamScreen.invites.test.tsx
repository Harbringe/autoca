import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { TeamScreen } from './TeamScreen'

vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true, refresh: vi.fn() }) }))
vi.mock('@/api/client', async (original) => {
  const actual = await original<typeof import('@/api/client')>()
  return { ...actual, raw: { ...actual.raw, post: vi.fn(), get: vi.fn(), delete: vi.fn() } }
})

const invite = (over: Record<string, unknown>) => ({
  id: 'i1',
  email: 'waiting@firm.test',
  full_name: '',
  role: 'STAFF',
  role_display: 'Staff',
  manager: null,
  expires_at: '2026-11-10T10:00:00Z',
  status: 'pending',
  created_at: '2026-11-03T10:00:00Z',
  created_by: 'asha@firm.test',
  ...over,
})

function answers(invites: unknown[]) {
  vi.mocked(raw.get).mockImplementation(((url: string) => {
    if (url.includes('/team/members/')) return Promise.resolve({ results: [], leads: [], can: { invite: true, manage: true, invite_roles: ['STAFF'] } })
    if (url.includes('/team/invites/')) return Promise.resolve({ results: invites })
    if (url.includes('/team/events/')) return Promise.resolve({ results: [] })
    return Promise.resolve({})
  }) as never)
}

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const root = createRootRoute()
  const page = createRoute({ getParentRoute: () => root, path: '/', component: () => <TeamScreen /> })
  const other = createRoute({ getParentRoute: () => root, path: '/$x/$y', component: () => <p>elsewhere</p> })
  const router = createRouter({ routeTree: root.addChildren([page, other]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('pending invitations on the Team screen', () => {
  beforeEach(() => {
    vi.mocked(raw.get).mockReset()
    vi.mocked(raw.post).mockReset()
  })

  it('says how each invitation stands: waiting, expiring soon or expired', async () => {
    answers([
      invite({ id: 'a', email: 'a@firm.test', status: 'pending' }),
      invite({ id: 'b', email: 'b@firm.test', status: 'expiring_soon' }),
      invite({ id: 'c', email: 'c@firm.test', status: 'expired' }),
    ])
    renderScreen()
    const table = await screen.findByRole('table', { name: 'Pending invitations' })
    expect(within(table).getByText('Waiting')).toBeInTheDocument()
    expect(within(table).getByText('Expires soon')).toBeInTheDocument()
    expect(within(table).getByText('Expired')).toBeInTheDocument()
  })

  it('makes a new link and shows it once, saying the old one no longer works', async () => {
    answers([invite({})])
    vi.mocked(raw.post).mockResolvedValue({ ...invite({ id: 'i2' }), link: 'https://app.test/invite/new.secret', emailed: false } as never)
    renderScreen()
    fireEvent.click(await screen.findByRole('button', { name: 'Make a new link for waiting@firm.test' }))
    expect(await screen.findByLabelText('Invitation link')).toHaveValue('https://app.test/invite/new.secret')
    expect(raw.post).toHaveBeenCalledWith('/api/v1/team/invites/i1/regenerate/', {})
    expect(screen.getByText(/old link no longer works/)).toBeInTheDocument()
  })

  it('gives an invitation another week', async () => {
    answers([invite({})])
    vi.mocked(raw.post).mockResolvedValue(invite({ expires_at: '2026-11-17T10:00:00Z' }) as never)
    renderScreen()
    fireEvent.click(await screen.findByRole('button', { name: 'Give waiting@firm.test another week' }))
    await waitFor(() => expect(raw.post).toHaveBeenCalledWith('/api/v1/team/invites/i1/extend/', {}))
  })

  it('offers Invite several beside Invite a person', async () => {
    answers([])
    renderScreen()
    expect(await screen.findByRole('button', { name: /Invite several/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Invite a person/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Invite several/ }))
    expect(await screen.findByLabelText('Email addresses')).toBeInTheDocument()
  })
})
