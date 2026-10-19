import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { gstRegistrations } from '@/api/queries/gst'
import { PortalConnection } from './PortalConnection'

const post = vi.fn()
const del = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn(), delete: (...a: unknown[]) => del(...a) } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

const GSTIN = '27AAAPL1234C1ZE'

function setup(connected: boolean) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } })
  queryClient.setQueryData(gstRegistrations('c1').queryKey, [{ id: 'r1', gstin: GSTIN, state_code: '27', registration_type: 'regular', portal_connected: connected, portal_username: connected ? 'owner@example.com' : '', portal_session_expires: connected ? '2026-10-19T18:00:00Z' : null }] as never)
  render(
    <QueryClientProvider client={queryClient}>
      <PortalConnection clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  post.mockReset()
  del.mockReset()
  post.mockResolvedValue({})
  del.mockResolvedValue(undefined)
})

describe('the GST portal connection on the client profile', () => {
  it('connects with the username and the OTP, without fetching anything', async () => {
    setup(false)
    expect(screen.getByText(/not connected/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^connect$/i }))
    await userEvent.type(screen.getByLabelText(/gst portal username/i), 'owner@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send otp/i }))
    await userEvent.type(await screen.findByLabelText(/otp from the portal/i), '123456')
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^connect$/i }))
    await waitFor(() => expect(post).toHaveBeenCalledWith(expect.stringContaining('/registrations/r1/portal/verify/'), { username: 'owner@example.com', otp: '123456' }))
    expect(post).not.toHaveBeenCalledWith(expect.stringContaining('portal-fetch'))
  })

  it('shows who is connected and disconnects', async () => {
    setup(true)
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText(/owner@example.com/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /disconnect/i }))
    await waitFor(() => expect(del).toHaveBeenCalledWith(expect.stringContaining('/registrations/r1/portal/')))
  })
})
