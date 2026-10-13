import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider, useSearch } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi, afterAll, beforeAll } from 'vitest'
import { journal, ledgers, parties, reviewQueue } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary, statements } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import { setSearchAllStatements } from '@/lib/reviewPrefs'
import { ReviewScreen } from './ReviewScreen'
import { setAllPageSize } from '@/lib/pageSizes'

vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))

const CLIENT = 'c1'

const row = (n: number, statement: string): Classification =>
  ({
    id: `r${n}`,
    transaction: { id: `t${n}`, statement, value_date: '2025-09-22', narration: `NARRATION ${n}`, amount_display: '₹1,000.00', amount_paise: 100000, is_debit: true, bank_account: 'b1' },
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

const STATEMENTS = {
  count: 2,
  results: [
    { id: 's2', bank_account_label: 'Icici Bank A/c 7921', period_start: '2025-04-03', period_end: '2026-03-31', transaction_count: 10 },
    { id: 's1', bank_account_label: 'Generic Bank A/c 5335', period_start: '2025-01-01', period_end: '2025-03-31', transaction_count: 6 },
  ],
}

function renderReview(rows: Classification[], { start = '/clients/c1/review', proposed = false } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Laxmi', can_post: true } as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 0, pending_approval: rows.length, total: rows.length, bulk_approvable: 0 } as never)
  queryClient.setQueryData(reviewQueue(CLIENT, 'pending_approval').queryKey, rows)
  queryClient.setQueryData(reviewQueue(CLIENT, 'unresolved').queryKey, [])
  queryClient.setQueryData(statements(CLIENT).queryKey, STATEMENTS as never)
  queryClient.setQueryData(
    ledgers(CLIENT).queryKey,
    (proposed ? [{ id: 'l9', name: 'Dividend Received', group: 'INDIRECT_INCOME', status: 'PROPOSED', is_active: true }] : []) as never,
  )
  queryClient.setQueryData(parties(CLIENT).queryKey, [])
  queryClient.setQueryData(journal(CLIENT).queryKey, [])
  queryClient.setQueryData(bankAccounts(CLIENT).queryKey, { count: 0, results: [] } as never)
  const root = createRootRoute()
  const review = createRoute({
    getParentRoute: () => root,
    path: '/clients/$clientId/review',
    validateSearch: (s: Record<string, unknown>) => ({ statement: typeof s.statement === 'string' ? s.statement : undefined }),
    component: () => <ReviewScreen clientId={CLIENT} stage="pending_approval" statement={(useSearch({ strict: false }) as { statement?: string }).statement} />,
  })
  const ledgersRoute = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/ledgers', component: () => <p>the ledgers page</p> })
  const mastersRoute = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/masters', component: () => <p>the parties page</p> })
  const router = createRouter({ routeTree: root.addChildren([review, ledgersRoute, mastersRoute]), history: createMemoryHistory({ initialEntries: [start] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const shown = () => [...document.querySelectorAll('ul[aria-label="Rows waiting"] > li')].map((li) => li.textContent ?? '')

// These count on pages of 50; lists start at 10, so say so.
beforeAll(() => setAllPageSize(50))
afterAll(() => setAllPageSize(null))

describe('the review, one bank statement at a time', () => {
  const rows = [row(1, 's2'), row(2, 's2'), row(3, 's2'), row(4, 's1'), row(5, 's1')]

  it('starts on the oldest statement with work and says how many each has', async () => {
    renderReview(rows)
    await screen.findByRole('group', { name: 'Statements to review' })
    expect(shown()).toHaveLength(2)
    expect(shown().join(' ')).toContain('NARRATION 4')
    expect(shown().join(' ')).not.toContain('NARRATION 1')
    expect(screen.getByRole('button', { name: /Generic Bank A\/c 5335 · 2/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /Icici Bank A\/c 7921 · 3/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /All statements · 5/ })).toBeInTheDocument()
  })

  it('ticks statements on and off, keeping the choice in the address', async () => {
    const router = renderReview(rows)
    // the oldest is on; ticking the other adds it, and with both on that is every statement
    fireEvent.click(await screen.findByRole('button', { name: /Icici Bank A\/c 7921 · 3/ }))
    await waitFor(() => expect(shown()).toHaveLength(5))
    expect(router.state.location.search).toMatchObject({ statement: 'all' })
    expect(shown().join(' ')).toContain('Generic Bank A/c 5335')

    // unticking the first leaves the other alone
    fireEvent.click(screen.getByRole('button', { name: /Generic Bank A\/c 5335 · 2/ }))
    await waitFor(() => expect(shown()).toHaveLength(3))
    expect(router.state.location.search).toMatchObject({ statement: 's2' })
    expect(shown().join(' ')).toContain('NARRATION 1')

    // the last one on cannot be switched off
    fireEvent.click(screen.getByRole('button', { name: /Icici Bank A\/c 7921 · 3/ }))
    expect(shown()).toHaveLength(3)

    fireEvent.click(screen.getByRole('button', { name: /All statements · 5/ }))
    await waitFor(() => expect(shown()).toHaveLength(5))
    expect(router.state.location.search).toMatchObject({ statement: 'all' })
  })

  it('opens on several statements when the address names them', async () => {
    renderReview(rows, { start: '/clients/c1/review?statement=s1,s2' })
    await waitFor(() => expect(shown()).toHaveLength(5))
    expect(screen.getByRole('button', { name: /Generic Bank A\/c 5335 · 2/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /Icici Bank A\/c 7921 · 3/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows the numbers of the statements chosen: the stage tabs, and what the screen says about the rows', async () => {
    renderReview(rows, { start: '/clients/c1/review?statement=s1' })
    await screen.findByRole('group', { name: 'Statements to review' })
    const nav = screen.getByRole('navigation', { name: 'Review stage' })
    const tab = (name: string) => within(nav).getByRole('link', { name: new RegExp(name) }).textContent
    expect(tab('Ready to post')).toContain('2')
    expect(tab('All waiting')).toContain('2')
    expect(tab('Needs a ledger')).toContain('0')
    // posted is what is on file in the statement (6) less what is still waiting (2)
    expect(tab('Posted')).toContain('4')
  })

  it('opens on the statement the address names', async () => {
    renderReview(rows, { start: '/clients/c1/review?statement=s2' })
    await screen.findByRole('group', { name: 'Statements to review' })
    expect(shown()).toHaveLength(3)
    expect(shown().join(' ')).toContain('NARRATION 1')
  })

  it('shows no picker when the rows belong to one statement', async () => {
    renderReview([row(1, 's2'), row(2, 's2')])
    await waitFor(() => expect(shown()).toHaveLength(2))
    expect(screen.queryByRole('group', { name: 'Statements to review' })).toBeNull()
  })
})

describe('"Look at them" on the assistant-added ledgers', () => {
  it('goes to the Ledgers page, not to Parties', async () => {
    const router = renderReview([row(1, 's2')], { proposed: true })
    const link = await screen.findByRole('link', { name: 'Look at them' })
    expect(link).toHaveAttribute('href', '/clients/c1/ledgers')
    fireEvent.click(link)
    await waitFor(() => expect(router.state.location.pathname).toBe('/clients/c1/ledgers'))
  })
})

describe('searching in the review', () => {
  const search = (text: string) => fireEvent.change(screen.getByLabelText(/Search the queue/), { target: { value: text } })

  it('looks through every row of the statement, not only the page on screen', async () => {
    const many = Array.from({ length: 120 }, (_, i) => row(i + 1, 's2'))
    renderReview(many, { start: '/clients/c1/review?statement=s2' })
    await screen.findByText('Showing 1–50 of 120')
    expect(document.getElementById('row-r110')).toBeNull()
    search('NARRATION 110')
    await waitFor(() => expect(shown()).toHaveLength(1))
    expect(shown()[0]).toContain('NARRATION 110')
  })

  it('stays inside the statement chosen, unless the setting to search every statement is on', async () => {
    setSearchAllStatements(false)
    renderReview([row(1, 's2'), row(2, 's2'), row(3, 's1'), row(4, 's1')], { start: '/clients/c1/review?statement=s1' })
    await screen.findByRole('group', { name: 'Statements to review' })
    search('NARRATION 1')
    await screen.findByText(/Nothing matches/)
    expect(shown()).toHaveLength(0)
  })

  it('looks through every statement when asked to, and says which statement each row is from', async () => {
    setSearchAllStatements(true)
    try {
      renderReview([row(1, 's2'), row(2, 's2'), row(3, 's1'), row(4, 's1')], { start: '/clients/c1/review?statement=s1' })
      await screen.findByRole('group', { name: 'Statements to review' })
      search('NARRATION 1')
      await waitFor(() => expect(shown()).toHaveLength(1))
      expect(shown()[0]).toContain('Icici Bank A/c 7921')
      expect(screen.getByRole('status', { name: '' })).toBeDefined()
      expect(screen.getByText(/Searching every statement/)).toBeInTheDocument()
    } finally {
      setSearchAllStatements(false)
    }
  })

  it('has a quick switch beside the search box that sets the same thing', async () => {
    setSearchAllStatements(false)
    renderReview([row(1, 's2'), row(3, 's1')], { start: '/clients/c1/review?statement=s1' })
    const box = await screen.findByLabelText('Search all statements')
    expect(box).not.toBeChecked()
    fireEvent.click(box)
    expect(box).toBeChecked()
    setSearchAllStatements(false)
  })
})
