import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { gstRegistrations, gstRuns } from '@/api/queries/gst'
import { ClientGst } from './ClientGst'

const remove = vi.fn()
const can = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { delete: (...a: unknown[]) => remove(...a), get: vi.fn(), post: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: (p: string) => can(p) }) }))
vi.mock('@/lib/title', () => ({ usePageTitle: () => {} }))

const CLIENT = 'c1'
const REG = { id: 'r1', gstin: '27AAAPL1234C1Z5', state_code: '27', registration_type: 'regular' }

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(gstRegistrations(CLIENT).queryKey, [REG] as never)
  queryClient.setQueryData(gstRuns(CLIENT).queryKey, [] as never)
  const root = createRootRoute()
  const page = createRoute({ getParentRoute: () => root, path: '/', component: () => <ClientGst clientId={CLIENT} /> })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  remove.mockReset()
  remove.mockResolvedValue(undefined)
  can.mockReset()
  can.mockReturnValue(true)
})

describe('removing a GSTIN', () => {
  it('asks first, says nothing is erased, and removes it when confirmed', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(await screen.findByRole('button', { name: 'Remove GSTIN 27AAAPL1234C1Z5' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Nothing is erased/)).toBeInTheDocument()
    expect(remove).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Remove GSTIN' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('/api/v1/clients/c1/gst/registrations/r1/'))
  })

  it('leaves the GSTIN alone when the person backs out', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(await screen.findByRole('button', { name: 'Remove GSTIN 27AAAPL1234C1Z5' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(remove).not.toHaveBeenCalled()
  })

  it('offers no Remove to a role that cannot prepare returns', async () => {
    can.mockImplementation((p: string) => p !== 'gst.prepare')
    setup()
    await screen.findByText('27AAAPL1234C1Z5')
    expect(screen.queryByRole('button', { name: /Remove GSTIN/ })).toBeNull()
  })
})
