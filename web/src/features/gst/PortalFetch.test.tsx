import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { gstRegistrations } from '@/api/queries/gst'
import { PortalFetch } from './PortalFetch'

const post = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn(), delete: vi.fn() } }))

const GSTIN = '27AAAPL1234C1ZE'
const REPORT = { id: 'run1', registration: { gstin: GSTIN } } as never

function setup(connected: boolean) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } })
  queryClient.setQueryData(gstRegistrations('c1').queryKey, [{ id: 'r1', gstin: GSTIN, state_code: '27', registration_type: 'regular', portal_connected: connected, portal_username: connected ? 'owner@example.com' : '', portal_session_expires: null }] as never)
  const onFetched = vi.fn()
  render(
    <QueryClientProvider client={queryClient}>
      <PortalFetch clientId="c1" report={REPORT} variant="secondary" onFetched={onFetched} />
    </QueryClientProvider>,
  )
  return onFetched
}

beforeEach(() => {
  post.mockReset()
  post.mockResolvedValue({ rows: 3, run: { id: 'run1' } })
})

describe('fetching GSTR-2B from the GST portal', () => {
  it('fetches in one click when the taxpayer is already signed in', async () => {
    const onFetched = setup(true)
    await userEvent.click(screen.getByRole('button', { name: /fetch from the gst portal/i }))
    await waitFor(() => expect(onFetched).toHaveBeenCalled())
    expect(post).toHaveBeenCalledWith(expect.stringContaining('/gst/runs/run1/portal-fetch/'))
  })

  it('signs in first with the username and the OTP, then fetches', async () => {
    const onFetched = setup(false)
    await userEvent.click(screen.getByRole('button', { name: /fetch from the gst portal/i }))
    await userEvent.type(screen.getByLabelText(/gst portal username/i), 'owner@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send otp/i }))
    expect(post).toHaveBeenCalledWith(expect.stringContaining('/registrations/r1/portal/otp/'), { username: 'owner@example.com' })
    await userEvent.type(await screen.findByLabelText(/otp from the portal/i), '123456')
    await userEvent.click(screen.getByRole('button', { name: /connect and fetch/i }))
    await waitFor(() => expect(onFetched).toHaveBeenCalled())
    expect(post).toHaveBeenCalledWith(expect.stringContaining('/registrations/r1/portal/verify/'), { username: 'owner@example.com', otp: '123456' })
    expect(post).toHaveBeenCalledWith(expect.stringContaining('/gst/runs/run1/portal-fetch/'))
  })

  it('shows the server’s words when the fetch is refused', async () => {
    const { ApiError } = await import('@/api/errors')
    post.mockRejectedValue(new ApiError(409, { code: 'gst_rule', detail: 'The portal has no GSTR-2B for that month yet.' }))
    setup(true)
    await userEvent.click(screen.getByRole('button', { name: /fetch from the gst portal/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/no GSTR-2B for that month/i)
  })
})
