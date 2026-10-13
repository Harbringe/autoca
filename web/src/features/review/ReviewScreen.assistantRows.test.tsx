import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { journal, ledgers, parties, reviewQueue } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import { IDLE_STATUS, type AssistantStatus } from '@/features/assistant/queue'
import { ReviewScreen } from './ReviewScreen'

const assistant: { status: AssistantStatus } = { status: IDLE_STATUS }
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@/features/assistant/useAssistant', async (original) => {
  const actual = await original<typeof import('@/features/assistant/useAssistant')>()
  return { ...actual, useAssistantStatus: () => assistant.status, useAssistantLine: () => ({ line: null, status: assistant.status }) }
})

const CLIENT = 'c1'
const WORKING: AssistantStatus = { state: 'working', reason: '', waiting: 3, total: 8, resumeAt: null }

const rowText = (n: number) => document.getElementById(`row-r${n}`)?.textContent ?? ''

const row = (n: number, over: Record<string, unknown>): Classification =>
  ({
    id: `r${n}`,
    transaction: { id: `t${n}`, value_date: '2025-09-22', narration: `NARRATION ${n}`, amount_display: '₹1,000.00', amount_paise: 100000, is_debit: true, bank_account: 'b1' },
    ledger: null,
    ledger_name: null,
    review_band: 'JUDGEMENT',
    method: 'UNRESOLVED',
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
    ...over,
  }) as unknown as Classification

function renderReview(rows: Classification[], stage: 'unresolved' | 'pending_approval' = 'unresolved') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Laxmi', can_post: true } as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: rows.length, pending_approval: rows.length, total: rows.length, bulk_approvable: 0 } as never)
  queryClient.setQueryData(reviewQueue(CLIENT, stage).queryKey, rows)
  queryClient.setQueryData(ledgers(CLIENT).queryKey, [])
  queryClient.setQueryData(parties(CLIENT).queryKey, [])
  queryClient.setQueryData(journal(CLIENT).queryKey, [])
  queryClient.setQueryData(bankAccounts(CLIENT).queryKey, { count: 0, results: [] } as never)
  const root = createRootRoute()
  const review = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/review', component: () => <ReviewScreen clientId={CLIENT} stage={stage} /> })
  const router = createRouter({ routeTree: root.addChildren([review]), history: createMemoryHistory({ initialEntries: ['/clients/c1/review'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  assistant.status = WORKING
})

describe('the assistant shown in the rows', () => {
  it('pulses where the ledger will appear for a row the assistant has, and says the rest are in line', async () => {
    renderReview([row(1, { model_state: 'claimed' }), row(2, { model_state: 'waiting' }), row(3, { model_state: null })])
    expect(await screen.findByText('Being read by the assistant')).toBeInTheDocument()
    expect(rowText(1)).toContain('Being read by the assistant')
    expect(rowText(2)).toContain('In line for the assistant')
    // a row nobody has queued is plainly in need of a person
    expect(rowText(3)).toContain('Needs a ledger')
  })

  it('does not say a row is in line when the assistant is off or paused', async () => {
    assistant.status = { state: 'paused', reason: 'daily_limit', waiting: 3, total: 8, resumeAt: null }
    renderReview([row(1, { model_state: 'claimed' }), row(2, { model_state: 'waiting' })])
    await screen.findAllByText('NARRATION 1')
    expect(screen.queryByText('Being read by the assistant')).toBeNull()
    expect(screen.queryByText('In line for the assistant')).toBeNull()
    expect(rowText(1)).toContain('Needs a ledger')
    expect(rowText(2)).toContain('Needs a ledger')
  })

  it('tags a placed row with who placed it, in words', async () => {
    renderReview(
      [
        row(1, { ledger: 'l1', ledger_name: 'Purchases', method: 'LLM', memory: { kind: 'ai', label: 'AI suggestion', note: 'Looks like a purchase.' } }),
        row(2, { ledger: 'l2', ledger_name: 'Bank Charges', method: 'RULE', memory: { kind: 'rule', label: 'Built-in rule', note: 'A built-in rule.' } }),
      ],
      'pending_approval',
    )
    expect((await screen.findAllByText('Assistant')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Rule').length).toBeGreaterThan(0)
  })
})
