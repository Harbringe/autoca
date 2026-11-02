import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { PfEsiWorking } from './PfEsiWorking'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), patch: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const REPORT = {
  year: 2025, month: 5, has_run: true, due: '2025-06-15',
  rows: [{ employee: 'Asha', uan: '', esic_number: '', gross_paise: 1200000, pf_wages_paise: 1200000, pf_employee_paise: 144000, pf_employer_paise: 144000, eps_paise: 99960, epf_paise: 44040, esi_applies: true, esi_employee_paise: 9000, esi_employer_paise: 39000 }],
  totals: {}, pf_total_paise: 288000, admin_charge_paise: 50000, edli_paise: 6000, esi_total_paise: 48000,
  pf_deposit: { deposited_on_time_paise: 0, deposited_late_paise: 0 }, esi_deposit: { deposited_on_time_paise: 0, deposited_late_paise: 0 },
  warnings: ['Asha: no UAN on file, so the ECR cannot name them.'],
}

function show(report: object) {
  vi.mocked(raw.get).mockResolvedValue(report)
  vi.mocked(raw.patch).mockResolvedValue({})
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PfEsiWorking clientId="c1" mayEdit people={[{ id: 'e1', name: 'Asha' }]} />
    </QueryClientProvider>,
  )
}

describe('PfEsiWorking', () => {
  it('shows the split, the warnings and what is due, and saves a UAN', async () => {
    show(REPORT)
    expect(await screen.findByText(/Asha: no UAN on file/)).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'PF and ESI by employee' })).toBeInTheDocument()
    expect(screen.getByText(/administration charge/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('UAN of Asha'), '100200300400')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(raw.patch).toHaveBeenCalledWith('/api/v1/clients/c1/employees/e1/', { uan: '100200300400', esic_number: '' }))
  })

  it('says so when no salary run is booked for the month', async () => {
    show({ year: 2025, month: 5, has_run: false, due: '2025-06-15' })
    expect(await screen.findByText('No salary run is booked for this month.')).toBeInTheDocument()
  })
})
