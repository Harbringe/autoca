import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clientDetail } from '@/api/queries/clients'
import type { Client } from '@/api/types'
import { BillPrint } from './BillPrint'

const get = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }))

const BILL = {
  id: 'b1',
  kind: 'SALES',
  kind_display: 'Sales invoice',
  party_name: 'Sunrise Traders',
  reference: 'INV-12',
  bill_date: '2026-10-05',
  due_date: '2026-11-04',
  taxable_paise: 100_000,
  cgst_paise: 9_000,
  sgst_paise: 9_000,
  igst_paise: 0,
  cess_paise: 0,
  round_off_paise: 0,
  tds_paise: 0,
  total_paise: 118_000,
  taxable_display: '1,000.00',
  cgst_display: '90.00',
  sgst_display: '90.00',
  igst_display: null,
  cess_display: null,
  round_off_display: null,
  total_display: '1,180.00',
  voucher_type: 'SALES',
  entry_no: 7,
}

function renderBill() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Acme Trading', address: '1 Main Road, Pune', pan: 'AAAAA0000A' } as unknown as Client)
  render(
    <QueryClientProvider client={queryClient}>
      <BillPrint clientId="c1" billId="b1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
  get.mockImplementation(async (url: string) => {
    if (url.includes('/bills/b1/')) return BILL
    if (url.includes('/gst/registrations/')) return { results: [{ id: 'r1', gstin: '27AAAAA0000A1Z5', state_code: '27' }] }
    throw new Error(`unexpected ${url}`)
  })
})

describe('BillPrint', () => {
  it('prints the firm, the party, the tax split and the total in words', async () => {
    renderBill()
    await waitFor(() => expect(screen.getByText('INV-12')).toBeInTheDocument())
    expect(screen.getByText('Acme Trading')).toBeInTheDocument()
    expect(await screen.findByText(/27AAAAA0000A1Z5/)).toBeInTheDocument()
    expect(screen.getByText('Sunrise Traders')).toBeInTheDocument()
    expect(screen.getByText('CGST')).toBeInTheDocument()
    expect(screen.getByText('SGST')).toBeInTheDocument()
    expect(screen.queryByText('IGST')).not.toBeInTheDocument()
    expect(screen.getByText('Rupees One Thousand One Hundred Eighty Only')).toBeInTheDocument()
  })

  it('has a Print button that is left off the paper', async () => {
    renderBill()
    const print = await screen.findByRole('button', { name: 'Print' })
    expect(print.closest('.no-print')).not.toBeNull()
  })
})
