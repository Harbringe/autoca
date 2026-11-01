import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clientDetail } from '@/api/queries/clients'
import type { Client } from '@/api/types'
import { VoucherPrint } from './VoucherPrint'

const get = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }))

const ENTRY = {
  id: 'e1',
  entry_no: 4,
  voucher_number: 'PMT/0004',
  voucher_type: 'PAYMENT',
  entry_date: '2026-10-09',
  narration: 'Rent for October',
  total_display: '25,000.00',
  total_paise: 2_500_000,
  lines: [
    { id: 'l1', ledger_name: 'Rent', party_name: null, direction: 'DR', amount_paise: 2_500_000, amount_display: '25,000.00' },
    { id: 'l2', ledger_name: 'HDFC Bank', party_name: null, direction: 'CR', amount_paise: 2_500_000, amount_display: '25,000.00' },
  ],
}

beforeEach(() => {
  get.mockReset()
  get.mockImplementation(async (url: string) => {
    if (url.includes('/journal-entries/e1/')) return ENTRY
    if (url.includes('/gst/registrations/')) return { results: [] }
    throw new Error(`unexpected ${url}`)
  })
})

describe('VoucherPrint', () => {
  it('prints the number, date, both sides and the narration', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Acme Trading' } as unknown as Client)
    render(
      <QueryClientProvider client={queryClient}>
        <VoucherPrint clientId="c1" entryId="e1" />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('PMT/0004')).toBeInTheDocument()
    expect(screen.getByText('Rent')).toBeInTheDocument()
    expect(screen.getByText('HDFC Bank')).toBeInTheDocument()
    expect(screen.getByText('Rent for October')).toBeInTheDocument()
    expect(screen.getByText('Rupees Twenty Five Thousand Only')).toBeInTheDocument()
  })
})
