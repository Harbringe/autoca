import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { journal, ledgerRows, ledgers } from '@/api/queries/books'
import { clientDetail } from '@/api/queries/clients'
import type { Client, LedgerAccount, LedgerRow } from '@/api/types'
import { MastersScreen } from './MastersScreen'

const setFy = vi.fn()
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2026, setFy, explicit: true, ready: true, dataYears: [2025, 2026] }) }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))

const CLIENT = 'c1'
const LEDGER = 'L1'

function row(id: string, fy: number, posted: boolean, narration: string): LedgerRow {
  return {
    id,
    transaction: `t-${id}`,
    value_date: `${fy}-02-02`,
    financial_year: fy,
    narration,
    book_narration: '',
    counterparty: '',
    amount_paise: 10000000,
    amount_display: '₹1,00,000.00',
    is_debit: true,
    is_posted: posted,
    needs_review: false,
    method: 'RULE',
    method_display: 'Rule',
  } as LedgerRow
}

function renderLedgers(rows: LedgerRow[]) {
  // Preloaded and never stale: the screen is drawn from exactly this data, with nothing fetched.
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(ledgers(CLIENT).queryKey, [
    { id: LEDGER, name: 'Investments - Shares & Mutual Funds', group: 'INVESTMENT', status: 'ACTIVE', is_active: true, row_count: rows.length },
  ] as unknown as LedgerAccount[])
  queryClient.setQueryData(journal(CLIENT).queryKey, [])
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, can_sign_off: false } as unknown as Client)
  queryClient.setQueryData(ledgerRows(CLIENT, LEDGER).queryKey, rows)
  const root = createRootRoute()
  const masters = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/review', component: () => <MastersScreen clientId={CLIENT} tab="ledgers" /> })
  const router = createRouter({ routeTree: root.addChildren([masters]), history: createMemoryHistory({ initialEntries: ['/clients/c1/review'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

beforeEach(() => setFy.mockClear())

describe('a ledger with rows placed but nothing under it', () => {
  const rows = [row('a', 2025, true, 'UPI/P2M/ZERODHA BROKING'), row('b', 2025, false, 'UPI/P2M/Smallcase')]

  it('labels the count as all years, so it is not read as this year', async () => {
    renderLedgers(rows)
    expect(await screen.findByRole('columnheader', { name: 'Rows placed (all years)' })).toBeInTheDocument()
  })

  it('says why there are no entries, instead of only saying there are none', async () => {
    renderLedgers(rows)
    await userEvent.click(await screen.findByRole('button', { name: 'Investments - Shares & Mutual Funds' }))
    expect(await screen.findByText('No posted entries for this ledger in FY 2026-27.')).toBeInTheDocument()
    expect(screen.getByText('1 row placed here has not been posted to the books yet.')).toBeInTheDocument()
    expect(screen.getByText('2 rows are dated in FY 2025-26.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Review to check and post them' })).toBeInTheDocument()
  })

  it('lists the placed rows with whether each is in the books', async () => {
    renderLedgers(rows)
    await userEvent.click(await screen.findByRole('button', { name: 'Investments - Shares & Mutual Funds' }))
    const table = await screen.findByRole('table', { name: 'Investments - Shares & Mutual Funds: rows placed, all years' })
    const listed = within(table).getAllByRole('row').slice(1)
    expect(listed).toHaveLength(2)
    expect(within(table).getByText('Posted')).toBeInTheDocument()
    expect(within(table).getByText('Not posted yet')).toBeInTheDocument()
  })

  it('offers a jump to the year the rows are in', async () => {
    renderLedgers(rows)
    await userEvent.click(await screen.findByRole('button', { name: 'Investments - Shares & Mutual Funds' }))
    await userEvent.click(await screen.findByRole('button', { name: 'FY 2025-26 · 2 rows' }))
    expect(setFy).toHaveBeenCalledWith(2025)
  })
})
