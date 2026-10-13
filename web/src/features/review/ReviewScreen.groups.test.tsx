import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { journal, ledgers, parties, reviewQueue } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary, statements } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import { setAllPageSize } from '@/lib/pageSizes'
import { ReviewScreen } from './ReviewScreen'

const post = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))

const CLIENT = 'c1'
const row = (n: number, counterparty: string, ledger = 'l1', ledgerName = 'Purchases', over: Record<string, unknown> = {}): Classification =>
  ({
    id: `r${n}`,
    transaction: { id: `t${n}`, statement: 's1', value_date: '2025-09-22', narration: `UPI/${n}/${counterparty}`, amount_display: '₹1,000.00', amount_paise: 100000, is_debit: true, bank_account: 'b1' },
    ledger,
    ledger_name: ledgerName,
    review_band: 'ADVISED',
    method: 'LLM',
    model_state: null,
    memory: null,
    is_posted: false,
    on_party_account: false,
    is_self_transfer: false,
    counterparty,
    party: null,
    party_candidates: [],
    suggested_ledger: null,
    entry_legs: [],
    ...over,
  }) as unknown as Classification

function setup(rows: Classification[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Laxmi', can_post: true } as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 0, pending_approval: rows.length, total: rows.length, bulk_approvable: 0 } as never)
  queryClient.setQueryData(reviewQueue(CLIENT, 'pending_approval').queryKey, rows)
  queryClient.setQueryData(reviewQueue(CLIENT, 'unresolved').queryKey, [])
  queryClient.setQueryData(statements(CLIENT).queryKey, { count: 1, results: [{ id: 's1', bank_account_label: 'Axis', period_start: '2025-04-01', period_end: '2026-03-31', transaction_count: rows.length }] } as never)
  queryClient.setQueryData(ledgers(CLIENT).queryKey, [])
  queryClient.setQueryData(parties(CLIENT).queryKey, [])
  queryClient.setQueryData(journal(CLIENT).queryKey, [])
  queryClient.setQueryData(bankAccounts(CLIENT).queryKey, { count: 0, results: [] } as never)
  const root = createRootRoute()
  const review = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/review', component: () => <ReviewScreen clientId={CLIENT} stage="pending_approval" /> })
  const router = createRouter({ routeTree: root.addChildren([review]), history: createMemoryHistory({ initialEntries: ['/clients/c1/review'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

const ROWS = [row(1, 'Ravi Traders'), row(2, 'RAVI TRADERS'), row(3, 'Ravi Traders'), row(4, 'Mehta Stores', 'l2', 'Repairs'), row(5, 'Ravi Traders', 'l1', 'Purchases', { on_party_account: true })]

beforeEach(() => {
  setAllPageSize(50)
  post.mockReset()
  post.mockResolvedValue([{ id: 'e1' }])
})

describe('seeing the ready rows as groups of alike ones', () => {
  it('offers the groups, each with its count, ledger and total, leaving out a row on a party’s own account', async () => {
    setup(ROWS)
    fireEvent.click(await screen.findByRole('button', { name: /Similar groups · 2/ }))
    const list = await screen.findByRole('list', { name: 'Groups of alike rows' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('Ravi Traders')
    expect(items[0]).toHaveTextContent('3')
    expect(items[0]).toHaveTextContent('Purchases')
    expect(items[0]).toHaveTextContent('₹3,000.00')
    expect(items[1]).toHaveTextContent('Mehta Stores')
  })

  it('posts a whole group at once, after asking, and posts exactly its rows', async () => {
    setup(ROWS)
    fireEvent.click(await screen.findByRole('button', { name: /Similar groups · 2/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Post all 3 rows like Ravi Traders' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/like “Ravi Traders”/)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Post 3' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0]![0]).toBe('/api/v1/clients/c1/approvals/')
    expect(post.mock.calls[0]![1]).toEqual({ classifications: ['r1', 'r2', 'r3'] })
  })

  it('opens one group’s rows in the ordinary list, with a way back', async () => {
    setup(ROWS)
    fireEvent.click(await screen.findByRole('button', { name: /Similar groups · 2/ }))
    fireEvent.click((await screen.findAllByRole('button', { name: 'Open rows' }))[1]!)
    await screen.findByText('Showing the rows of one group.')
    await waitFor(() => expect(document.querySelectorAll('ul[aria-label="Rows waiting"] > li')).toHaveLength(1))
    fireEvent.click(screen.getByRole('button', { name: 'Show every row' }))
    await waitFor(() => expect(document.querySelectorAll('ul[aria-label="Rows waiting"] > li').length).toBeGreaterThan(1))
  })
})
