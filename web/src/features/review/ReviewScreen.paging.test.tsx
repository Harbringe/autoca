import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { journal, ledgers, parties, reviewQueue } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import { ReviewScreen } from './ReviewScreen'

vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))

const CLIENT = 'c1'

const row = (n: number): Classification =>
  ({
    id: `r${n}`,
    transaction: { id: `t${n}`, value_date: '2025-09-22', narration: `NARRATION ${n}`, amount_display: '₹1,000.00', amount_paise: 100000, is_debit: true, bank_account: 'b1' },
    ledger: 'l1',
    ledger_name: 'Purchases',
    review_band: 'ADVISED',
    method: 'LLM',
    model_state: null,
    memory: null,
    is_posted: false,
    on_party_account: false,
    is_self_transfer: false,
    counterparty: '',
    party: null,
    party_candidates: [],
    suggested_ledger: null,
    entry_legs: [],
  }) as unknown as Classification

function renderReview(count: number) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  const rows = Array.from({ length: count }, (_, i) => row(i + 1))
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Laxmi', can_post: true } as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 0, pending_approval: count, total: count, bulk_approvable: 0 } as never)
  queryClient.setQueryData(reviewQueue(CLIENT, 'pending_approval').queryKey, rows)
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

const rowsOnScreen = () => document.querySelectorAll('ul[aria-label="Rows waiting"] > li').length

describe('a long review queue is shown a page at a time', () => {
  it('shows one page of rows and a pager when there are many', async () => {
    renderReview(120)
    await screen.findByText('Showing 1–50 of 120')
    expect(rowsOnScreen()).toBe(50)
    expect(document.getElementById('row-r1')).not.toBeNull()
    expect(document.getElementById('row-r51')).toBeNull()
  })

  it('turns to the next page and selects the first row on it', async () => {
    renderReview(120)
    await screen.findByText('Showing 1–50 of 120')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Showing 51–100 of 120')
    expect(document.getElementById('row-r51')).not.toBeNull()
    expect(document.getElementById('row-r1')).toBeNull()
    await waitFor(() => expect(document.getElementById('row-r51')).toHaveAttribute('aria-expanded', 'true'))
  })

  it('has no pager for a short queue', async () => {
    renderReview(30)
    await screen.findAllByText(/NARRATION 1\b/)
    expect(rowsOnScreen()).toBe(30)
    expect(screen.queryByRole('navigation', { name: /pages/ })).toBeNull()
  })
})
