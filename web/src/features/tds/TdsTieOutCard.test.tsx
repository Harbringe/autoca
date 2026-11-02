import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { TdsTieOutCard } from './TdsTieOutCard'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))

const q = (n: number, o: object = {}) => ({
  quarter: n, bills_paise: 0, credited_from_bills_paise: 0, credited_other_paise: 0, bills_difference_paise: 0,
  deducted_paise: 0, deposited_paise: 0, with_challan_paise: 0, without_challan_paise: 0, ...o,
})

function show(body: object) {
  vi.mocked(raw.get).mockResolvedValue(body)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TdsTieOutCard clientId="c1" />
    </QueryClientProvider>,
  )
}

describe('TdsTieOutCard', () => {
  it('says what is still to deposit when everything agrees', async () => {
    show({ fy: 2025, quarters: [q(1, { bills_paise: 10000, credited_from_bills_paise: 10000 }), q(2), q(3), q(4)], deducted_paise: 10000, deposited_paise: 0, still_to_deposit_paise: 10000, without_section_paise: 0, agrees: true, has_ledger: true })
    expect(await screen.findByText(/agree\. Still to deposit/)).toBeInTheDocument()
  })

  it('names a deposit with no challan and deductions with no section', async () => {
    show({ fy: 2025, quarters: [q(1, { deposited_paise: 5000, without_challan_paise: 5000 }), q(2), q(3), q(4)], deducted_paise: 0, deposited_paise: 5000, still_to_deposit_paise: -5000, without_section_paise: 2000, agrees: false, has_ledger: true })
    expect(await screen.findByText(/does not agree/)).toBeInTheDocument()
    expect(screen.getByText(/no section/)).toBeInTheDocument()
  })

  it('shows nothing when there is no TDS Payable ledger', async () => {
    show({ fy: 2025, quarters: [], deducted_paise: 0, deposited_paise: 0, still_to_deposit_paise: 0, without_section_paise: 0, agrees: true, has_ledger: false })
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByLabelText('TDS against the books')).not.toBeInTheDocument()
  })
})
