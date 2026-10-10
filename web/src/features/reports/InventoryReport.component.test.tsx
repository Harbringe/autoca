import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { InventoryReport } from './InventoryReport'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, ...rest }: { children: React.ReactNode }) => <a {...(rest as object)}>{children}</a>,
}))

const footer = { client_name: 'Shri Narayan Trading Company Loha', financial_year: 2025, period_start: '2025-04-01', period_end: '2026-03-31', entry_count: 5, pending_review: 0, generated_at: '2026-10-08T10:00:00Z', fy_label: '2025-26', is_complete: true }

const month = (m: string, over: Record<string, unknown> = {}) => ({
  month: m, in_qty: '0', in_value_paise: 0, out_qty: '0', out_value_paise: 0, closing_qty: '0', closing_value_paise: 0, ...over,
})

const REPORT = {
  footer,
  bills_counted: 3,
  bills_left_out: 2,
  left_out_examples: ['SN4048 (Shri Padmavati Trading Co)'],
  lines_without_value: 0,
  items: [
    {
      name: 'CEMENT SUPER NEW', unit: 'BAG', opening_qty: '0', opening_value_paise: 0, closing_qty: '-30', closing_value_paise: 0,
      in_qty: '100', in_value_paise: 3000000, out_qty: '130', out_value_paise: 4550000,
      months: [
        month('2025-04', { in_qty: '100', in_value_paise: 3000000, out_qty: '40', out_value_paise: 1400000, closing_qty: '60', closing_value_paise: 1800000 }),
        month('2025-05', { out_qty: '90', out_value_paise: 3150000, closing_qty: '-30', closing_value_paise: 0 }),
      ],
    },
  ],
}

function renderIt(data = REPORT) {
  vi.mocked(raw.get).mockResolvedValue(data)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <InventoryReport clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

describe('the inventory report', () => {
  it('shows inwards, outwards and closing for each month of the item', async () => {
    renderIt()
    const table = await screen.findByRole('table', { name: 'Monthly summary of CEMENT SUPER NEW' })
    const april = within(table).getByText('April').closest('tr')!
    expect(within(april).getByText('100 BAG')).toBeInTheDocument()
    expect(within(april).getByText('60 BAG')).toBeInTheDocument()
    expect(within(table).getByText('Grand total')).toBeInTheDocument()
  })

  it('shows a quantity that went below nothing in brackets, not hidden', async () => {
    renderIt()
    const table = await screen.findByRole('table', { name: 'Monthly summary of CEMENT SUPER NEW' })
    expect(within(table).getAllByText('(30 BAG)').length).toBeGreaterThan(0)
  })

  it('says which bills it could not use', async () => {
    renderIt()
    expect(await screen.findByText(/no invoice\s+lines with a quantity/)).toBeInTheDocument()
    expect(screen.getByText(/SN4048 \(Shri Padmavati Trading Co\)/)).toBeInTheDocument()
  })

  it('says so when there is nothing to show', async () => {
    renderIt({ ...REPORT, items: [], bills_left_out: 0, bills_counted: 0 })
    expect(await screen.findByText('No stock movements yet')).toBeInTheDocument()
  })
})
