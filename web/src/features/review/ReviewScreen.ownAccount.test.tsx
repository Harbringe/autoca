import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { journal, ledgers, parties, reviewQueue } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import { ReviewScreen } from './ReviewScreen'

vi.mock('@/api/queries/clients', async (original) => ({
  ...(await original<typeof import('@/api/queries/clients')>()),
  useInvalidateClient: () => () => Promise.resolve([]),
}))

const permissions = { party: true }
vi.mock('@/session/session', () => ({
  useSession: () => ({ me: { permissions: [] }, can: (p: string) => (p === 'party.manage' ? permissions.party : true) }),
}))
vi.mock('@/api/client', async (original) => {
  const actual = await original<typeof import('@/api/client')>()
  return { ...actual, raw: { ...actual.raw, post: vi.fn(), get: vi.fn(), delete: vi.fn() } }
})

const CLIENT = 'c1'

const row = (over: Record<string, unknown> = {}): Classification =>
  ({
    id: 'r1',
    transaction: { id: 't1', value_date: '2025-04-01', narration: 'UPI-SAMPLEPERSON', amount_display: '₹10,000.00', amount_paise: 1000000, is_debit: false, bank_account: 'b1' },
    ledger: 'L1',
    ledger_name: 'Sales',
    review_band: 'JUDGEMENT',
    method: 'LLM',
    confidence: 0.5,
    is_posted: false,
    on_party_account: false,
    is_self_transfer: false,
    counterparty: 'SAMPLE PERSON',
    party: null,
    party_candidates: [],
    rcm: false,
    tds_section: '',
    open_question: 'Who paid this?',
    suggested_ledger: null,
    entry_legs: [
      { side: 'Dr', ledger: 'Generic Bank A/c', amount_display: '₹10,000.00', is_bank: true },
      { side: 'Cr', ledger: 'Sales', amount_display: '₹10,000.00', is_bank: false },
    ],
    ...over,
  }) as unknown as Classification

// The real screen refetches after it opens the account. Here the refetch is stubbed and the account is put in the cached ledger list, which
// is what the refetch would have brought back.
let queryClient: QueryClient

function renderReview(rows: Classification[]) {
  queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Laxmi', can_post: true } as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 0, pending_approval: rows.length, total: rows.length, bulk_approvable: 0 } as never)
  queryClient.setQueryData(reviewQueue(CLIENT, 'pending_approval').queryKey, rows)
  queryClient.setQueryData(ledgers(CLIENT).queryKey, [{ id: 'L1', name: 'Sales', group: 'DIRECT_INCOME', status: 'ACTIVE', is_active: true }] as never)
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

const offer = () => screen.queryByRole('button', { name: /Use a different ledger|^Use Sample Person/ })

beforeEach(() => {
  permissions.party = true
  vi.mocked(raw.post).mockReset()
  vi.mocked(raw.post).mockImplementation(((url: string, body: Record<string, unknown>) => {
    if (url.endsWith('/parties/')) return Promise.resolve({ id: 'p1', canonical_name: body.canonical_name })
    if (url.endsWith('/account/')) {
      const account = { id: 'L9', name: 'Sample Person', group: 'DEBTOR', status: 'ACTIVE', is_active: true }
      queryClient.setQueryData(ledgers(CLIENT).queryKey, (old: unknown[] | undefined) => [...(old ?? []), account] as never)
      return Promise.resolve(account)
    }
    return Promise.resolve({ classification: { ledger_name: 'Sample Person' }, rule_learned: null, also_placed: 0, auto_posted: 0 })
  }) as never)
})

describe("offering the payee's own account when the narration names a person", () => {
  it('names the payee as a person would write it and offers a customer account for a receipt', async () => {
    renderReview([row()])
    expect(await screen.findByRole('button', { name: 'Use a different ledger' })).toBeInTheDocument()
    expect(screen.getByText(/own account \(a new customer account/)).toBeInTheDocument()
  })

  it('offers a supplier account, and says debit, for a payment', async () => {
    renderReview([row({ transaction: { id: 't1', value_date: '2025-04-01', narration: 'UPI-SAMPLEPERSON', amount_display: '₹500.00', amount_paise: 50000, is_debit: true, bank_account: 'b1' } })])
    expect(await screen.findByRole('button', { name: 'Use a different ledger' })).toBeInTheDocument()
    expect(screen.getByText(/own account \(a new supplier account/)).toBeInTheDocument()
  })

  it('is chosen from the start: placing the row makes the party and its account, then books the row to that account under that party', async () => {
    renderReview([row()])
    expect(await screen.findByText(/Not saved yet/)).toBeInTheDocument()
    // Nothing is made or booked until the person places the row.
    expect(vi.mocked(raw.post)).not.toHaveBeenCalled()

    fireEvent.click(await screen.findByRole('button', { name: /Place in ledger/ }))
    await waitFor(() => expect(vi.mocked(raw.post).mock.calls.some(([url]) => String(url).includes('/review/'))).toBe(true))
    const made = vi.mocked(raw.post).mock.calls.find(([url]) => String(url).endsWith('/parties/'))
    expect(made![1]).toEqual({ canonical_name: 'Sample Person', role: 'CUSTOMER' })
    expect(vi.mocked(raw.post).mock.calls.some(([url]) => String(url).endsWith('/parties/p1/account/'))).toBe(true)
    const placed = vi.mocked(raw.post).mock.calls.find(([url]) => String(url).includes('/review/'))
    expect(placed![1]).toMatchObject({ ledger: 'L9', party: 'p1' })
  })

  it('can be set aside for a general ledger, and then the ledger picker is back', async () => {
    renderReview([row()])
    fireEvent.click(await screen.findByRole('button', { name: 'Use a different ledger' }))
    expect(await screen.findByRole('button', { name: 'Use Sample Person’s own account' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Ledger \(the other side of the entry\)/)).toBeInTheDocument()
  })

  it('offers to give every named person their own account at once, and places each one’s rows', async () => {
    renderReview([
      row(),
      row({ id: 'r2', transaction: { id: 't2', value_date: '2025-04-02', narration: 'UPI-OTHERPERSON', amount_display: '₹200.00', amount_paise: 20000, is_debit: false, bank_account: 'b1' }, counterparty: 'OTHER PERSON' }),
    ])
    fireEvent.click(await screen.findByRole('button', { name: /Give 2 named people their own accounts \(2\)/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Place 2 rows' }))

    await waitFor(() => expect(vi.mocked(raw.post).mock.calls.filter(([url]) => String(url).includes('/review/')).length).toBe(2))
    const names = vi.mocked(raw.post).mock.calls.filter(([url]) => String(url).endsWith('/parties/')).map(([, body]) => (body as { canonical_name: string }).canonical_name)
    expect(names.sort()).toEqual(['Other Person', 'Sample Person'])
    const placed = vi.mocked(raw.post).mock.calls.filter(([url]) => String(url).includes('/review/')).map(([, body]) => body)
    expect(placed.every((b) => (b as { ledger: string }).ledger === 'L9')).toBe(true)
  })

  it.each([
    ['a party is already known for the row', { party: 'p0' }],
    ['the system suggests a party the person can confirm', { party_candidates: [{ party: 'p0', name: 'Sample Persons', why: 'close' }] }],
    ['a rule placed it', { method: 'RULE' }],
    ['a person already decided it', { method: 'REVIEWED' }],
    ['the assistant is quite sure of the ledger', { confidence: 0.9 }],
    ['no payee could be read', { counterparty: '' }],
    ['it moves money between the client’s own accounts', { is_self_transfer: true }],
  ])('says nothing when %s', async (_why, over) => {
    renderReview([row(over)])
    await screen.findAllByText(/UPI-SAMPLEPERSON/)
    expect(offer()).toBeNull()
  })

  it('says nothing to someone who may not manage parties', async () => {
    permissions.party = false
    renderReview([row()])
    await screen.findAllByText(/UPI-SAMPLEPERSON/)
    expect(offer()).toBeNull()
  })
})
