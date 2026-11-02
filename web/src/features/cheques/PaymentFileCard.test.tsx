import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { PaymentFileCard } from './PaymentFileCard'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), put: vi.fn(), postBlob: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const saveFile = vi.fn()
vi.mock('@/platform/download', () => ({ saveFile: (...a: unknown[]) => saveFile(...a) }))

const OWED = [
  { party: 'p1', name: 'Ravi Traders', open_paise: 10000000, bills: 1, ready: true, account_last4: '6789' },
  { party: 'p2', name: 'Shah & Co', open_paise: 500000, bills: 2, ready: false, account_last4: '' },
]

function show() {
  vi.mocked(raw.get).mockImplementation(((url: string) => Promise.resolve(url.includes('/accounts/') ? [{ id: 'a1', label: 'AXIS ••••7214' }] : OWED)) as never)
  vi.mocked(raw.postBlob).mockResolvedValue({ blob: new Blob(['x']), filename: 'payments-2026-11-04-neft.csv' })
  vi.mocked(raw.put).mockResolvedValue({})
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PaymentFileCard clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('PaymentFileCard', () => {
  it('shows who is owed and who has no bank details, and builds the file for the ones ticked', async () => {
    show()
    expect(await screen.findByText('No bank details')).toBeInTheDocument()
    expect(screen.getByText('Account ••••6789')).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Pay Ravi Traders'))
    await userEvent.click(screen.getByRole('button', { name: 'Prepare payment file' }))
    await waitFor(() =>
      expect(raw.postBlob).toHaveBeenCalledWith('/api/v1/clients/c1/payment-files/', expect.objectContaining({ bank_account: 'a1', mode: 'NEFT', items: [{ party: 'p1', amount_paise: 10000000 }] })),
    )
    await waitFor(() => expect(saveFile).toHaveBeenCalledWith('payments-2026-11-04-neft.csv', expect.any(Blob)))
  })

  it('saves a party\'s bank details', async () => {
    show()
    await userEvent.click((await screen.findAllByRole('button', { name: 'Add details' }))[0]!)
    await userEvent.type(screen.getByLabelText('Account number of Shah & Co'), '50100123456789')
    await userEvent.type(screen.getByLabelText('IFSC of Shah & Co'), 'HDFC0001234')
    await userEvent.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() =>
      expect(raw.put).toHaveBeenCalledWith('/api/v1/clients/c1/parties/p2/payment-details/', { account_number: '50100123456789', ifsc: 'HDFC0001234', account_name: 'Shah & Co' }),
    )
  })

  it('shows nothing when nobody is owed', async () => {
    vi.mocked(raw.get).mockResolvedValue([])
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PaymentFileCard clientId="c2" />
      </QueryClientProvider>,
    )
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByLabelText('Bank payment file')).not.toBeInTheDocument()
  })
})
