import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { InviteScreen } from './InviteScreen'

vi.mock('@/session/session', () => ({ useSession: () => ({ refresh: () => Promise.resolve() }) }))
vi.mock('@/api/client', async (original) => {
  const actual = await original<typeof import('@/api/client')>()
  return { ...actual, raw: { ...actual.raw, post: vi.fn(), get: vi.fn() } }
})

const DESCRIPTION = { email: 'new.person@example.test', full_name: '', firm: 'Sample Firm', role_display: 'Staff', team: '' }

function renderInvite() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const root = createRootRoute()
  const invite = createRoute({ getParentRoute: () => root, path: '/invite/$token', component: () => <InviteScreen token="firm.secret" /> })
  const home = createRoute({ getParentRoute: () => root, path: '/', component: () => <p>home</p> })
  const router = createRouter({ routeTree: root.addChildren([invite, home]), history: createMemoryHistory({ initialEntries: ['/invite/firm.secret'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('InviteScreen', () => {
  beforeEach(() => {
    vi.mocked(raw.post).mockReset()
    vi.mocked(raw.get).mockReset()
    vi.mocked(raw.post).mockImplementation(((url: string) => (url.endsWith('/describe/') ? Promise.resolve(DESCRIPTION) : Promise.resolve({}))) as never)
  })

  it('asks about the invite with the token in the body, never in the URL', async () => {
    renderInvite()
    await screen.findByText(/Sample Firm/)
    expect(raw.post).toHaveBeenCalledWith('/auth/invite/describe/', { token: 'firm.secret' })
    expect(raw.get).not.toHaveBeenCalled()
  })

  it('does not say whether the address has an account: one form for a new person and for an existing one', async () => {
    renderInvite()
    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('Your name')).toBeInTheDocument()
    expect(screen.queryByText(/already have an account, so use its password/i)).toBeNull()
  })

  it('sends the name and the password together, and the server decides what they mean', async () => {
    renderInvite()
    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'a-long-enough-phrase-1' } })
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Sample Person' } })
    fireEvent.click(screen.getByRole('button', { name: /Accept invitation/ }))
    await waitFor(() =>
      expect(raw.post).toHaveBeenCalledWith('/auth/invite/', { token: 'firm.secret', password: 'a-long-enough-phrase-1', full_name: 'Sample Person' }),
    )
  })
})
