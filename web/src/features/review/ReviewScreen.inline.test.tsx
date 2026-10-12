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

const row = (n: number, narration: string): Classification =>
  ({
    id: `r${n}`,
    transaction: { id: `t${n}`, value_date: '2025-09-22', narration, amount_display: '₹1,000.00', amount_paise: 100000, is_debit: true, bank_account: 'b1' },
    ledger: null,
    ledger_name: null,
    review_band: 'JUDGEMENT',
    method: 'UNRESOLVED',
    is_posted: false,
    on_party_account: false,
    is_self_transfer: false,
    counterparty: '',
    party: null,
    party_candidates: [],
    entry_legs: [
      { side: 'Dr', ledger: null, amount_display: '₹1,000.00', is_bank: false },
      { side: 'Cr', ledger: 'Generic Bank A/c 0365', amount_display: '₹1,000.00', is_bank: true },
    ],
  }) as unknown as Classification

function renderReview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Divine', can_post: true } as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 2, pending_approval: 0, total: 2, bulk_approvable: 0 } as never)
  queryClient.setQueryData(reviewQueue(CLIENT, 'unresolved').queryKey, [row(1, 'PAID TO FIRST PAYEE'), row(2, 'PAID TO SECOND PAYEE')])
  queryClient.setQueryData(ledgers(CLIENT).queryKey, [])
  queryClient.setQueryData(parties(CLIENT).queryKey, [])
  queryClient.setQueryData(journal(CLIENT).queryKey, [])
  queryClient.setQueryData(bankAccounts(CLIENT).queryKey, { count: 0, results: [] } as never)
  const root = createRootRoute()
  const review = createRoute({
    getParentRoute: () => root,
    path: '/clients/$clientId/review',
    component: () => <ReviewScreen clientId={CLIENT} stage="unresolved" />,
  })
  const router = createRouter({ routeTree: root.addChildren([review]), history: createMemoryHistory({ initialEntries: ['/clients/c1/review'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('the review queue, inline', () => {
  it('opens the decision under the selected row and moves it when another row is chosen', async () => {
    renderReview()
    expect((await screen.findAllByText(/PAID TO FIRST PAYEE/)).length).toBeGreaterThan(0)
    // The first row is open by default, directly under itself.
    expect(document.getElementById('decision-r1')).not.toBeNull()
    expect(document.getElementById('decision-r2')).toBeNull()
    expect(document.getElementById('row-r1')).toHaveAttribute('aria-expanded', 'true')
    expect(document.getElementById('row-r1')!.closest('li')).toContainElement(document.getElementById('decision-r1'))
    expect(screen.getAllByText('The entry this makes')).toHaveLength(1)

    fireEvent.click(document.getElementById('row-r2')!)
    expect(document.getElementById('row-r1')).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById('row-r2')).toHaveAttribute('aria-expanded', 'true')
    expect(document.getElementById('row-r2')!.closest('li')).toContainElement(document.getElementById('decision-r2'))
    // The row that was open stays on screen while it closes, then goes.
    await waitFor(() => expect(document.getElementById('decision-r1')).toBeNull())
    expect(screen.getAllByText('The entry this makes')).toHaveLength(1)
  })

  it('shuts the open row when it is pressed again, and keeps its place', async () => {
    renderReview()
    await screen.findAllByText(/PAID TO FIRST PAYEE/)
    fireEvent.click(document.getElementById('row-r1')!)
    expect(document.getElementById('row-r1')).toHaveAttribute('aria-expanded', 'false')
    await waitFor(() => expect(document.getElementById('decision-r1')).toBeNull())
    fireEvent.click(document.getElementById('row-r1')!)
    expect(document.getElementById('decision-r1')).not.toBeNull()
  })
})
