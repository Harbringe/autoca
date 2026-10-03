import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { journal } from '@/api/queries/books'
import { reviewSummary } from '@/api/queries/clients'
import type { JournalEntry, ReviewSummary } from '@/api/types'
import { PostedEntries } from './PostedEntries'

vi.mock('@/session/session', () => ({
  useSession: () => ({ me: { permissions: ['journal.view'] }, can: () => true }),
}))

const CLIENT = 'c1'

function entry(n: number, date: string, fy: number, narration: string, debit: string, credit = 'Axis Bank A/c 7214'): JournalEntry {
  return {
    id: `e${n}`,
    entry_no: n,
    voucher_type: 'Payment',
    entry_date: date,
    financial_year: fy,
    fy_label: `${fy}-${String((fy + 1) % 100).padStart(2, '0')}`,
    narration,
    total_display: '₹1,000.00',
    marker_display: '',
    lines: [
      { id: `l${n}a`, ledger_account: debit, ledger_name: debit, direction: 'DR', amount_paise: 100000 },
      { id: `l${n}b`, ledger_account: credit, ledger_name: credit, direction: 'CR', amount_paise: 100000 },
    ],
  } as unknown as JournalEntry
}

const ENTRIES = [
  entry(1, '2025-07-01', 2025, 'Being sweep debit charged by bank', 'Bank Charges'),
  entry(2, '2026-02-02', 2025, 'Being UPI paid to Zerodha', 'Investments - Shares & Mutual Funds'),
  entry(3, '2026-04-04', 2026, 'Being UPI paid to Rajveer', 'Drawings'),
]

function renderTab(entries: JournalEntry[] = ENTRIES) {
  // Preloaded and never stale, so nothing is fetched: the screen is drawn from exactly this data.
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(journal(CLIENT).queryKey, entries)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 0, pending_approval: 0, total: 0 } as unknown as ReviewSummary)
  const root = createRootRoute()
  const review = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/review', component: () => <PostedEntries clientId={CLIENT} /> })
  const router = createRouter({ routeTree: root.addChildren([review]), history: createMemoryHistory({ initialEntries: ['/clients/c1/review'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('Posted tab', () => {
  it('lists every posted entry, in every year, newest first', async () => {
    renderTab()
    const table = await screen.findByRole('table', { name: 'Posted entries, newest first' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('Rajveer')
    expect(rows[2]).toHaveTextContent('sweep debit')
    expect(screen.getByText('3 entries')).toBeInTheDocument()
  })

  it('narrows to one financial year', async () => {
    renderTab()
    await screen.findByRole('table')
    await userEvent.selectOptions(screen.getByLabelText('Financial year'), '2026')
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('Rajveer')
  })

  it('searches the narration and the ledger names', async () => {
    renderTab()
    await screen.findByRole('table')
    await userEvent.type(screen.getByLabelText('Search posted entries'), 'investments')
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('Zerodha')
  })

  it('says so when nothing has been posted, and points to where posting happens', async () => {
    renderTab([])
    expect(await screen.findByText('Nothing has been posted yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ready to post' })).toBeInTheDocument()
  })
})
