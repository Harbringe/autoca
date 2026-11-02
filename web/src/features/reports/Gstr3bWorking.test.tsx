import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { Gstr3bWorking } from './Gstr3bWorking'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), put: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

const tax = (o: object = {}) => ({ igst_paise: 0, cgst_paise: 0, sgst_paise: 0, cess_paise: 0, ...o })
const REPORT = {
  month: '2025-04',
  outward_taxable: { taxable_paise: 1500000, ...tax({ cgst_paise: 135000 }) },
  zero_rated_paise: 0,
  exempt_nil_paise: 0,
  non_gst_outward_paise: 0,
  inward_reverse_charge: { taxable_paise: 0, ...tax() },
  inward_exempt_paise: 0,
  itc_all_other: { taxable_paise: 0, ...tax({ cgst_paise: 90000 }) },
  itc_reverse_charge: { taxable_paise: 0, ...tax() },
  itc_reversed: tax(),
  opening_credit: tax(),
  liability: tax({ cgst_paise: 135000 }),
  paid_by_credit: tax({ cgst_paise: 90000 }),
  paid_in_cash: tax({ cgst_paise: 45000 }),
  interest: tax(),
  late_fee_paise: 0,
  carry_forward: tax(),
  untaxed_sales_paise: 200000,
  untaxed_unexplained_paise: 200000,
  counts: { sales: 1, purchases: 1, reverse_charge: 0 },
  entries: { exempt_paise: 0, opening_credit_cgst_paise: null },
}

function show() {
  vi.mocked(raw.get).mockResolvedValue(REPORT)
  vi.mocked(raw.put).mockResolvedValue(REPORT)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Gstr3bWorking clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

describe('Gstr3bWorking', () => {
  it('shows the tables, flags sales with no tax, and asks for another month when changed', async () => {
    show()
    expect(await screen.findByText('3.1(a) Outward taxable supplies')).toBeInTheDocument()
    expect(screen.getByText('6.1 Paid through credit')).toBeInTheDocument()
    expect(screen.getByText(/carry no tax/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2025-10' } })
    await waitFor(() => expect(raw.get).toHaveBeenCalledWith('/api/v1/clients/c1/reports/gstr3b/', { month: '2025-10' }))
  })

  it('saves the month\'s entries in paise, leaving an opening credit empty as not entered', async () => {
    show()
    await userEvent.type(await screen.findByLabelText('Nil-rated and exempt supplies (3.1(c))'), '1500.50')
    await userEvent.click(screen.getByRole('button', { name: 'Save for this month' }))
    await waitFor(() =>
      expect(raw.put).toHaveBeenCalledWith(
        '/api/v1/clients/c1/reports/gstr3b/?month=2025-04',
        expect.objectContaining({ exempt_paise: 150050, opening_credit_cgst_paise: null }),
      ),
    )
  })
})
