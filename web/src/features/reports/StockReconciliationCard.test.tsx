import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { StockReconciliationCard } from './StockReconciliationCard'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))

function show(body: object) {
  vi.mocked(raw.get).mockResolvedValue(body)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StockReconciliationCard clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

const base = { fy: 2025, as_at: '2026-03-31', register_value_paise: 400000, books_value_paise: 0, difference_paise: 400000 }

describe('StockReconciliationCard', () => {
  it('names what does not agree and what to do about it', async () => {
    show({
      ...base,
      agrees: false,
      checks: [
        { key: 'value', title: 'Stock value against the books', status: 'attention', message: 'The register says more than the ledgers.', examples: [] },
        { key: 'unlisted', title: 'Items missing from the item list', status: 'attention', message: '1 item is not listed.', examples: ['Mustard Oil 1L'] },
      ],
    })
    expect(await screen.findByText(/The register says more than the ledgers/)).toBeInTheDocument()
    expect(screen.getByText(/Mustard Oil 1L/)).toBeInTheDocument()
  })

  it('says so when everything agrees', async () => {
    show({ ...base, difference_paise: 0, books_value_paise: 400000, agrees: true, checks: [{ key: 'value', title: 'v', status: 'ok', message: 'fine', examples: [] }] })
    expect(await screen.findByText(/agree/)).toBeInTheDocument()
  })

  it('takes the register figure as the closing stock when asked', async () => {
    vi.mocked(raw.post).mockResolvedValue({})
    show({ ...base, agrees: false, checks: [{ key: 'value', title: 'Stock value against the books', status: 'attention', message: 'Gap.', examples: [] }] })
    await userEvent.click(await screen.findByRole('button', { name: "Use the register's closing stock" }))
    await waitFor(() => expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/reports/stock-reconciliation/use-register/?fy=2025', {}))
  })
})
