import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { ChequesScreen } from './ChequesScreen'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('./PaymentFileCard', () => ({ PaymentFileCard: () => null }))
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig<object>()),
  Link: ({ children, ...p }: { children: React.ReactNode } & Record<string, unknown>) => <a href="#" aria-label={p['aria-label'] as string}>{children}</a>,
}))

const CHEQUE = {
  id: 'q1', bank_account: 'a1', bank_label: 'AXIS ••••7214', direction: 'ISSUED', number: '000101', cheque_date: '2026-12-01', issued_on: '2026-11-01', amount_paise: 500000,
  party: null, party_name: '', payee_name: 'Sharma Traders', print_name: 'Sharma Traders', status: 'PENDING', status_display: 'Not yet presented', status_on: null, note: '',
  is_post_dated: true, is_stale: false,
}
const PDC = { issued_paise: 500000, received_paise: 0, by_month: [{ month: '2026-12', issued_paise: 500000, received_paise: 0 }], due_soon: [], stale: [] }

function show(mayEdit = true) {
  vi.mocked(raw.get).mockImplementation(((url: string) => {
    if (url.includes('/pdc/')) return Promise.resolve(PDC)
    if (url.includes('/accounts/')) return Promise.resolve([{ id: 'a1', label: 'AXIS ••••7214' }])
    return Promise.resolve({ results: [CHEQUE], next: null, count: 1 })
  }) as never)
  vi.mocked(raw.post).mockResolvedValue({})
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ChequesScreen clientId="c1" mayEdit={mayEdit} />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('ChequesScreen', () => {
  it('lists cheques with post-dated ones marked and summarises what is waiting', async () => {
    show()
    expect(await screen.findByText('Sharma Traders')).toBeInTheDocument()
    expect(screen.getByText('post-dated')).toBeInTheDocument()
    expect(await screen.findByText(/Issued, waiting to be presented/)).toBeInTheDocument()
  })

  it('records a cheque in paise', async () => {
    show()
    await userEvent.type(await screen.findByLabelText('Cheque number'), '000102')
    await userEvent.type(screen.getByLabelText('Cheque amount'), '2500.50')
    await userEvent.type(screen.getByLabelText('Payee'), 'Rao & Sons')
    await userEvent.click(screen.getByRole('button', { name: 'Record cheque' }))
    await waitFor(() =>
      expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/cheques/', expect.objectContaining({ bank_account: 'a1', direction: 'ISSUED', number: '000102', amount_paise: 250050, payee_name: 'Rao & Sons' })),
    )
  })

  it('marks a pending cheque cleared', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Mark cheque 000101 cleared' }))
    await waitFor(() => expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/cheques/q1/status/', { status: 'CLEARED' }))
  })

  it('offers no changes to someone who may not edit', async () => {
    show(false)
    await screen.findByText('Sharma Traders')
    expect(screen.queryByLabelText('Record a cheque')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /cleared/ })).not.toBeInTheDocument()
  })
})
