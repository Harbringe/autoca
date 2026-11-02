import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { godowns } from '@/api/queries/godowns'
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
  below_reorder: 1,
  quantities_only: false,
  items: [
    {
      name: 'CEMENT SUPER NEW', unit: 'BAG', opening_qty: '0', opening_value_paise: 0, closing_qty: '-30', closing_value_paise: 0,
      in_qty: '100', in_value_paise: 3000000, out_qty: '130', out_value_paise: 4550000,
      reorder_level: '25', below_reorder: true,
      movements: [
        { date: '2025-04-05', direction: 'IN', quantity: '100', value_paise: 3000000, source: 'Purchase P-4 · Ravi Traders' },
        { date: '2025-04-20', direction: 'OUT', quantity: '40', value_paise: 1400000, source: 'Sales INV-9 · Sunrise Traders' },
      ],
      months: [
        month('2025-04', { in_qty: '100', in_value_paise: 3000000, out_qty: '40', out_value_paise: 1400000, closing_qty: '60', closing_value_paise: 1800000 }),
        month('2025-05', { out_qty: '90', out_value_paise: 3150000, closing_qty: '-30', closing_value_paise: 0 }),
      ],
    },
  ],
}

const RECON = { fy: 2025, as_at: '2026-03-31', register_value_paise: 0, books_value_paise: 0, difference_paise: 0, agrees: true, checks: [] }

function renderIt(data = REPORT) {
  vi.mocked(raw.get).mockImplementation(((url: string) => Promise.resolve(url.includes('stock-reconciliation') ? RECON : data)) as never)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <InventoryReport clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

describe('the inventory report by godown', () => {
  it('offers a godown picker only when the client has godowns, and asks for that godown', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    queryClient.setQueryData(godowns('c1').queryKey, [{ id: 'g1', name: 'Shop' }])
    vi.mocked(raw.get).mockImplementation(((url: string) => Promise.resolve(url.includes('stock-reconciliation') ? RECON : REPORT)) as never)
    render(
      <QueryClientProvider client={queryClient}>
        <InventoryReport clientId="c1" fy={2025} />
      </QueryClientProvider>,
    )
    const picker = await screen.findByLabelText('Location')
    await userEvent.selectOptions(picker, 'Shop')
    await waitFor(() => expect(raw.get).toHaveBeenLastCalledWith('/api/v1/clients/c1/reports/inventory/', { fy: 2025, godown: 'g1' }))
  })

  it('has no picker when there are no godowns', async () => {
    renderIt()
    await screen.findByRole('table', { name: 'Monthly summary of CEMENT SUPER NEW' })
    expect(screen.queryByLabelText('Location')).not.toBeInTheDocument()
  })

  it('shows quantities only, and says why, for a single godown', async () => {
    renderIt({ ...REPORT, quantities_only: true } as typeof REPORT)
    const table = await screen.findByRole('table', { name: 'Monthly summary of CEMENT SUPER NEW' })
    expect(screen.getByText(/shows quantities only/)).toBeInTheDocument()
    expect(within(table).queryByText('Value')).not.toBeInTheDocument()
  })
})

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

  it('says how many items are at or below their reorder level, and marks each one', async () => {
    renderIt()
    expect(await screen.findByRole('status')).toHaveTextContent(/1 item is at or below its reorder level/)
    expect(screen.getByText('Reorder at 25 BAG')).toBeInTheDocument()
  })

  it('does not mention reordering when nothing is low', async () => {
    renderIt({ ...REPORT, below_reorder: 0, items: [{ ...REPORT.items[0]!, below_reorder: false }] })
    await screen.findByRole('table', { name: 'Monthly summary of CEMENT SUPER NEW' })
    expect(screen.queryByText(/reorder level/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Reorder at/)).not.toBeInTheDocument()
  })

  it('lists the movements of an item with where each came from', async () => {
    renderIt()
    const table = await screen.findByRole('table', { name: 'Movements of CEMENT SUPER NEW' })
    const purchase = within(table).getByText('Purchase P-4 · Ravi Traders').closest('tr')!
    expect(within(purchase).getByText('05-04-2025')).toBeInTheDocument()
    expect(within(purchase).getByText('100 BAG')).toBeInTheDocument()
    const sale = within(table).getByText('Sales INV-9 · Sunrise Traders').closest('tr')!
    expect(within(sale).getByText('40 BAG')).toBeInTheDocument()
  })

  it('says so when there is nothing to show', async () => {
    renderIt({ ...REPORT, items: [], bills_left_out: 0, bills_counted: 0 })
    expect(await screen.findByText('No stock movements yet')).toBeInTheDocument()
  })
})
