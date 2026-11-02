import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { StockVouchers } from './StockVouchers'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))

const row = (o: object) => ({ id: 'x', kind: 'ADJUSTMENT', kind_display: 'Stock adjustment', entry_date: '2025-06-10', direction: 'OUT', name: 'Rice', unit: 'Bag', quantity: '2.000', note: '', ...o })

function show(results: object[]) {
  vi.mocked(raw.get).mockResolvedValue({ results })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StockVouchers clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

describe('StockVouchers', () => {
  it("lists the year's stock entries that carry no accounting entry", async () => {
    show([row({}), row({ id: 'y', kind: 'OPENING', kind_display: 'Opening stock', direction: 'IN', quantity: '40.000', entry_date: '2025-04-01' }), row({ id: 'z', entry_date: '2024-05-01', name: 'Last year' })])
    expect(await screen.findByText('Stock adjustment')).toBeInTheDocument()
    expect(screen.getByText('+40 Bag')).toBeInTheDocument()
    expect(screen.queryByText('Last year')).not.toBeInTheDocument()
  })

  it('shows nothing when the year has none', async () => {
    show([row({ kind: 'TALLY' })])
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByLabelText('Stock vouchers')).not.toBeInTheDocument()
  })
})
