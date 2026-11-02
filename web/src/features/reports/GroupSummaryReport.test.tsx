import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { GroupSummaryReport } from './GroupSummaryReport'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))

const GROUPS = {
  fy: 2025,
  groups: [
    {
      group: 'PURCHASE', label: 'Purchase Accounts', opening_paise: 0, debit_paise: 1200000, credit_paise: 0, closing_paise: 1200000,
      ledgers: [{ ledger_id: 'l1', name: 'Purchases', opening_paise: 0, debit_paise: 1200000, credit_paise: 0, closing_paise: 1200000 }],
    },
  ],
  total_debit_paise: 1200000,
  total_credit_paise: 1200000,
}
const MONTHLY = {
  fy: 2025,
  ledger: { id: 'l1', name: 'Purchases', group: 'PURCHASE', group_label: 'Purchase Accounts' },
  opening_paise: 0,
  months: [{ month: '2025-10', debit_paise: 1000000, credit_paise: 0, closing_paise: 1000000 }],
  total_debit_paise: 1000000,
  total_credit_paise: 0,
  closing_paise: 1000000,
}

describe('GroupSummaryReport', () => {
  it('opens a group to its ledgers and a ledger to its months', async () => {
    vi.mocked(raw.get).mockImplementation(((url: string) => Promise.resolve(url.includes('ledger-monthly') ? MONTHLY : GROUPS)) as never)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <GroupSummaryReport clientId="c1" fy={2025} />
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /Purchase Accounts/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Purchases' }))
    expect(await screen.findByRole('table', { name: 'Purchases by month' })).toBeInTheDocument()
    await waitFor(() => expect(raw.get).toHaveBeenCalledWith('/api/v1/clients/c1/reports/ledger-monthly/', { fy: 2025, ledger: 'l1' }))
    await userEvent.click(screen.getByRole('button', { name: 'Back to groups' }))
    expect(await screen.findByRole('table', { name: 'Group summary' })).toBeInTheDocument()
  })
})
