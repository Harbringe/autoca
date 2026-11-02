import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { ledgers } from '@/api/queries/books'
import { BudgetReport } from './BudgetReport'
import { CostCentresReport } from './CostCentresReport'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

const wrap = (ui: React.ReactNode, setup?: (qc: QueryClient) => void) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  setup?.(qc)
  render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => vi.clearAllMocks())

describe('BudgetReport', () => {
  it('shows budget, actual and variance and saves a month for a ledger', async () => {
    vi.mocked(raw.get).mockResolvedValue({
      fy: 2025, through: null,
      ledgers: [{ ledger_id: 'l1', ledger: 'Contract Work', is_income: false, budget_paise: 800000, actual_paise: 1000000, variance_paise: 200000,
        months: [{ month: '2025-10', budget_paise: 800000, actual_paise: 1000000, variance_paise: 200000 }] }],
    })
    vi.mocked(raw.put).mockResolvedValue([])
    wrap(<BudgetReport clientId="c1" fy={2025} />, (qc) => qc.setQueryData(ledgers('c1').queryKey, [{ id: 'l1', name: 'Contract Work', status: 'ACTIVE' }] as never))
    expect(await screen.findByRole('table', { name: 'Budget for Contract Work' })).toBeInTheDocument()
    expect(screen.getByText(/overspending/)).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Ledger to budget'), 'Contract Work')
    await userEvent.type(screen.getByLabelText('Budget for 2025-10'), '8000')
    await userEvent.click(screen.getByRole('button', { name: 'Save budget' }))
    await waitFor(() => expect(raw.put).toHaveBeenCalledWith('/api/v1/clients/c1/budgets/set/', { fy: 2025, ledger: 'l1', months: { '2025-10': 800000 } }))
  })
})

describe('CostCentresReport', () => {
  it('adds a cost centre and shows what is not tagged', async () => {
    vi.mocked(raw.get).mockResolvedValue({
      fy: 2025,
      centres: [{ id: 'k1', name: 'Pune Site', income_paise: 0, expense_paise: 600000, net_paise: -600000, ledgers: [{ ledger: 'Contract Work', is_income: false, amount_paise: 600000 }] }],
      unallocated_income_paise: 0, unallocated_expense_paise: 400000,
    })
    vi.mocked(raw.post).mockResolvedValue({ id: 'k2', name: 'Goa Site' })
    wrap(<CostCentresReport clientId="c1" fy={2025} />)
    expect(await screen.findByText('Pune Site')).toBeInTheDocument()
    expect(screen.getByText('Not tagged to any cost centre')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Cost centre name'), 'Goa Site')
    await userEvent.click(screen.getByRole('button', { name: 'Add cost centre' }))
    await waitFor(() => expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/cost-centres/', { name: 'Goa Site' }))
  })
})
