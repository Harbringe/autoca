import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { Gstr1Working } from './Gstr1Working'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))

const section = (rows: object[] = []) => ({ rows, total: {} })
const row = { number: 'B-1', date: '2025-04-05', party: 'Mehta Stores', gstin: '27AAAAA0000A1Z5', value_paise: 1180000, taxable_paise: 1000000, rate: '18', igst_paise: 0, cgst_paise: 90000, sgst_paise: 90000, cess_paise: 0 }
const REPORT = {
  month: '2025-04',
  b2b: section([row]),
  b2cl: section(),
  b2cs: { rows: [{ supply: 'Intra-state', rate: '18', taxable_paise: 500000, igst_paise: 0, cgst_paise: 45000, sgst_paise: 45000, cess_paise: 0 }] },
  credit_notes_registered: section(),
  credit_notes_unregistered: section(),
  exempt_nil_non_gst: { zero_rated_paise: 0, exempt_paise: 0, non_gst_paise: 0, untaxed_sales_paise: 0 },
  hsn: [{ hsn: '1514', unit: 'Nos', quantity: 40, taxable_paise: 1000000, igst_paise: 0, cgst_paise: 90000, sgst_paise: 90000, cess_paise: 0 }],
  hsn_bills_without_items: 1,
  documents: [{ label: 'Invoices for outward supply', from: 'B-1', to: 'C-2', count: 3 }],
  agrees_with_3b: true,
  taxable_in_tables_paise: 1500000,
  taxable_in_3b_paise: 1500000,
}

describe('Gstr1Working', () => {
  it('lists the tables, says it agrees with the 3B working, and asks for another month when changed', async () => {
    vi.mocked(raw.get).mockResolvedValue(REPORT)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Gstr1Working clientId="c1" fy={2025} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('4 · B2B invoices (to registered parties)')).toBeInTheDocument()
    expect(screen.getByText('Mehta Stores')).toBeInTheDocument()
    expect(screen.getByText('7 · B2C other, by rate')).toBeInTheDocument()
    expect(screen.getByText('12 · HSN summary')).toBeInTheDocument()
    expect(screen.getByText(/The taxable value in these tables is the outward supplies/)).toBeInTheDocument()
    expect(screen.getByText(/1 invoice\(s\) have no item lines/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('GSTR-1 month'), { target: { value: '2025-10' } })
    await waitFor(() => expect(raw.get).toHaveBeenCalledWith('/api/v1/clients/c1/reports/gstr1/', { month: '2025-10' }))
  })
})
