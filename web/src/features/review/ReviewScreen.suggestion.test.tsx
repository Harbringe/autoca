import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { journal, ledgers, parties, reviewQueue } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import { ReviewScreen } from './ReviewScreen'

const permissions = { manage: true }
vi.mock('@/session/session', () => ({
  useSession: () => ({ me: { permissions: [] }, can: (p: string) => (p === 'ledger.manage' ? permissions.manage : true) }),
}))
vi.mock('@/api/client', async (original) => {
  const actual = await original<typeof import('@/api/client')>()
  return { ...actual, raw: { ...actual.raw, post: vi.fn(), get: vi.fn(), delete: vi.fn() } }
})

const CLIENT = 'c1'

const suggestion = (over: Record<string, unknown> = {}) => ({
  name: 'Dividend Received',
  group: 'INDIRECT_INCOME',
  group_display: 'Indirect Incomes',
  existing_ledger: null,
  existing_name: null,
  rows_sharing: 2,
  ...over,
})

const row = (n: number, over: Record<string, unknown> = {}): Classification =>
  ({
    id: `r${n}`,
    transaction: { id: `t${n}`, value_date: '2025-09-22', narration: `ACH CREDIT ${n}`, amount_display: '₹7.40', amount_paise: 740, is_debit: false, bank_account: 'b1' },
    ledger: 'L1',
    ledger_name: 'Bank Interest Received',
    review_band: 'JUDGEMENT',
    method: 'LLM',
    confidence: 0.6,
    is_posted: false,
    on_party_account: false,
    is_self_transfer: false,
    counterparty: '',
    party: null,
    party_candidates: [],
    rcm: false,
    tds_section: '',
    open_question: 'Is this a dividend or interest?',
    suggested_ledger: suggestion(),
    entry_legs: [
      { side: 'Dr', ledger: 'Generic Bank A/c', amount_display: '₹7.40', is_bank: true },
      { side: 'Cr', ledger: 'Bank Interest Received', amount_display: '₹7.40', is_bank: false },
    ],
    ...over,
  }) as unknown as Classification

const ledger = (id: string, name: string, group: string) => ({ id, name, group, status: 'ACTIVE', is_active: true }) as never

function renderReview(rows: Classification[], { haveDividend = false } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Laxmi', can_post: true } as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 0, pending_approval: rows.length, total: rows.length, bulk_approvable: 0 } as never)
  queryClient.setQueryData(reviewQueue(CLIENT, 'pending_approval').queryKey, rows)
  queryClient.setQueryData(ledgers(CLIENT).queryKey, [ledger('L1', 'Bank Interest Received', 'INDIRECT_INCOME'), ...(haveDividend ? [ledger('L2', 'Dividend Received', 'INDIRECT_INCOME')] : [])])
  queryClient.setQueryData(parties(CLIENT).queryKey, [])
  queryClient.setQueryData(journal(CLIENT).queryKey, [])
  queryClient.setQueryData(bankAccounts(CLIENT).queryKey, { count: 0, results: [] } as never)
  const root = createRootRoute()
  const review = createRoute({
    getParentRoute: () => root,
    path: '/clients/$clientId/review',
    component: () => <ReviewScreen clientId={CLIENT} stage="pending_approval" />,
  })
  const router = createRouter({ routeTree: root.addChildren([review]), history: createMemoryHistory({ initialEntries: ['/clients/c1/review'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

const reviewCalls = () => vi.mocked(raw.post).mock.calls.filter(([url]) => String(url).includes('/review/'))

beforeEach(() => {
  permissions.manage = true
  vi.mocked(raw.post).mockReset()
  vi.mocked(raw.post).mockImplementation(((url: string, body: Record<string, unknown>) => {
    if (url.endsWith('/ledgers/')) return Promise.resolve({ id: 'L9', name: body.name, group: body.group })
    return Promise.resolve({ classification: { ledger_name: 'Dividend Received' }, rule_learned: null, also_placed: 0, auto_posted: 0 })
  }) as never)
})

describe('a ledger the assistant suggested but was not sure enough to open', () => {
  it('shows the idea with the question, and says how many other rows carry it', async () => {
    renderReview([row(1)])
    expect(await screen.findByLabelText('Suggested ledger')).toHaveTextContent('Dividend Received')
    expect(screen.getByLabelText('Suggested ledger')).toHaveTextContent('not sure enough to open one')
    expect(screen.getByLabelText('Suggested ledger')).toHaveTextContent('2 other waiting rows carry the same suggestion')
    expect(screen.getByText('Is this a dividend or interest?')).toBeInTheDocument()
    expect(screen.getAllByText('Ledger idea').length).toBeGreaterThan(0)
  })

  it('creates the ledger the person confirms and places the row in that new ledger, not the old one', async () => {
    renderReview([row(1)])
    fireEvent.click(await screen.findByRole('button', { name: /Create “Dividend Received” and place this row/ }))
    // the dialog opens with the suggested name and kind, which can still be changed
    expect(await screen.findByDisplayValue('Dividend Received')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create and use' }))

    await waitFor(() => expect(reviewCalls()).toHaveLength(1))
    expect(vi.mocked(raw.post).mock.calls.some(([url, body]) => String(url).endsWith('/ledgers/') && (body as { group: string }).group === 'INDIRECT_INCOME')).toBe(true)
    expect(reviewCalls()[0]![1]).toMatchObject({ ledger: 'L9' })
  })

  it('places the row straight into the ledger when the client already has one by that name', async () => {
    renderReview([row(1, { suggested_ledger: suggestion({ existing_ledger: 'L2', existing_name: 'Dividend Received' }) })], { haveDividend: true })
    fireEvent.click(await screen.findByRole('button', { name: 'Place in Dividend Received' }))

    await waitFor(() => expect(reviewCalls()).toHaveLength(1))
    expect(reviewCalls()[0]![1]).toMatchObject({ ledger: 'L2' })
    expect(vi.mocked(raw.post).mock.calls.some(([url]) => String(url).endsWith('/ledgers/'))).toBe(false)
  })

  it('shows the idea as words only to someone who may not add ledgers', async () => {
    permissions.manage = false
    renderReview([row(1)])
    expect(await screen.findByLabelText('Suggested ledger')).toHaveTextContent('Someone who can add ledgers can create it')
    expect(screen.queryByRole('button', { name: /Create “Dividend Received”/ })).toBeNull()
  })

  it('shows nothing when there is no suggestion', async () => {
    renderReview([row(1, { suggested_ledger: null })])
    await screen.findAllByText(/ACH CREDIT 1/)
    expect(screen.queryByLabelText('Suggested ledger')).toBeNull()
    expect(screen.queryByText('Ledger idea')).toBeNull()
  })
})
