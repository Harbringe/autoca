import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { Gstr3bWorking } from './Gstr3bWorking'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))

const row = (o: object = {}) => ({ taxable_paise: 0, igst_paise: 0, cgst_paise: 0, sgst_paise: 0, cess_paise: 0, ...o })

describe('Gstr3bWorking', () => {
  it('shows the tables for the chosen month and asks for another when changed', async () => {
    vi.mocked(raw.get).mockResolvedValue({
      month: '2025-04',
      outward_taxable: row({ taxable_paise: 1500000, cgst_paise: 135000 }),
      inward_reverse_charge: row(),
      itc_all_other: row({ cgst_paise: 90000 }),
      itc_reverse_charge: row(),
      payable: { igst_paise: 0, cgst_paise: 45000, sgst_paise: 0, cess_paise: 0 },
      counts: { sales: 1, purchases: 1, reverse_charge: 0 },
      not_covered: ['Interest and late fee'],
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Gstr3bWorking clientId="c1" fy={2025} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('3.1(a) Outward taxable supplies')).toBeInTheDocument()
    expect(screen.getByText('6.1 Tax payable')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2025-10' } })
    await waitFor(() => expect(raw.get).toHaveBeenCalledWith('/api/v1/clients/c1/reports/gstr3b/', { month: '2025-10' }))
  })
})
