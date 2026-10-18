import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GstinCheckPanel } from './GstinCheck'

const post = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn() } }))

const ANSWER = {
  gstin: '27AAAPL1234C1ZE',
  outcome: 'found',
  status: 'active',
  details: { legal_name: 'RAVI TRADERS PRIVATE LIMITED', trade_name: 'RAVI TRADERS', registration_type: 'Regular', state: 'Maharashtra', address: 'Pune', pincode: '411001' },
  checked_at: '2026-10-18T10:00:00Z',
  from_cache: false,
  provider: 'StubGstinVerifier',
  message: '',
  party_name: 'Ravi Stores',
  name_matches: false,
  cancelled: false,
}

function setup(onUseName = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
      <GstinCheckPanel clientId="c1" partyId="p1" bookName="Ravi Stores" onUseName={onUseName} />
    </QueryClientProvider>,
  )
  return onUseName
}

beforeEach(() => post.mockReset())

describe('checking a party’s GSTIN with the portal', () => {
  it('shows what the portal says, flags a different name, and puts the portal name in the form only when asked', async () => {
    post.mockResolvedValue(ANSWER)
    const onUseName = setup()
    await userEvent.click(screen.getByRole('button', { name: /check with the gst portal/i }))
    expect(await screen.findByText('RAVI TRADERS PRIVATE LIMITED')).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith(expect.stringContaining('/gst/gstin-check/'), { party: 'p1', refresh: false })
    expect(screen.getByText('Name differs')).toBeInTheDocument()
    expect(onUseName).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /use the portal.s legal name/i }))
    expect(onUseName).toHaveBeenCalledWith('RAVI TRADERS PRIVATE LIMITED')
  })

  it('says a cancelled GSTIN is cancelled', async () => {
    post.mockResolvedValue({ ...ANSWER, status: 'cancelled', cancelled: true, name_matches: true })
    setup()
    await userEvent.click(screen.getByRole('button', { name: /check with the gst portal/i }))
    expect(await screen.findByText(/GSTIN cancelled/)).toBeInTheDocument()
  })

  it('says so when the portal has no record, and offers no name to copy', async () => {
    post.mockResolvedValue({ ...ANSWER, outcome: 'not_found', details: {}, status: 'not found', message: 'The portal has no record of this GSTIN.', name_matches: null })
    setup()
    await userEvent.click(screen.getByRole('button', { name: /check with the gst portal/i }))
    expect(await screen.findByText('Not on the portal')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /use the portal/i })).toBeNull()
  })
})
