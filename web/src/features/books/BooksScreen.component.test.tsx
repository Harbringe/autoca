import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { closeReport } from '@/api/queries/bills'
import { journal } from '@/api/queries/books'
import { booksStatus, clientDetail } from '@/api/queries/clients'
import { BooksScreen } from './BooksScreen'

vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

const CHECKS = [
  { name: 'rows_posted', title: 'Every bank row is placed and posted', ok: false, detail: '11 transactions still need a decision.' },
  { name: 'assistant_entries_checked', title: 'Entries the assistant posted are checked by a person', ok: false, detail: '2 entries not yet marked as checked.' },
  { name: 'suspense_clear', title: 'Nothing is left in Suspense', ok: true, detail: '' },
  { name: 'bank_b1', title: 'Generic Bank A/c 0365 agrees with its statement', ok: false, detail: 'It does not reconcile at 06-01-2026. The books say ₹1,24,66,449.31; the bank says ₹13,83,437.31; the difference is ₹1,10,83,012.00.' },
]

const entry = (n: number) => ({ id: `e${n}`, entry_no: n, voucher_type: 'Payment', entry_date: '2025-04-12', narration: `Bank charges ${n}`, total_display: '₹2.65', marker: 'AI_POSTED', marker_display: 'Posted by the AI' })

function renderIt() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Divine', can_post: true, lead: { id: 'u1', name: 'owner_rudra' } } as never)
  queryClient.setQueryData(booksStatus('c1').queryKey, {
    signed_off_through: null,
    review_pending: false,
    requested_by: '',
    requested_at: null,
    returned_note: '',
    approved_through: null,
    approved_by: '',
    approved_at: null,
    changed_since_approval: 0,
    close_period: 'QUARTERLY',
    sealable_dates: [],
    next_seal_date: '2025-06-30',
    waiting: 12,
    ai_posted: 2,
    ai_revised: 0,
    can_request: false,
    can_sign_off: true,
    history: [],
  } as never)
  queryClient.setQueryData(closeReport('c1').queryKey, { through: null, ready: false, unexplained_blocking: 0, checks: CHECKS, items: [] } as never)
  queryClient.setQueryData(journal('c1').queryKey, [entry(1), entry(2)] as never)
  render(
    <QueryClientProvider client={queryClient}>
      <BooksScreen clientId="c1" />
    </QueryClientProvider>,
  )
}

describe('sign-off checklist', () => {
  it('says what is left in one sentence and lists the failing checks with their figures', async () => {
    renderIt()
    expect(await screen.findByText('Three things to clear before you can send the books for review.')).toBeInTheDocument()
    expect(screen.getByText('11 to decide')).toBeInTheDocument()
    expect(screen.getByText('2 to check')).toBeInTheDocument()
    expect(screen.getByText('₹1,10,83,012.00')).toBeInTheDocument()
  })

  it('opens the first failing check, and folds the passing one into a single line', async () => {
    renderIt()
    expect(await screen.findByRole('link', { name: 'Open Review' })).toBeInTheDocument()
    const fold = screen.getByRole('button', { name: /1 check passes/ })
    expect(fold).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(fold)
    expect(screen.getByText('Nothing is left in Suspense')).toBeInTheDocument()
  })

  it('lets assistant entries be ticked one at a time and marked as checked', async () => {
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: /Entries the assistant posted are checked/ }))
    const first = screen.getByRole('checkbox', { name: 'Mark Payment 1 as checked' })
    const button = screen.getByRole('button', { name: /Mark selected as checked/ })
    expect(button).toBeDisabled()
    fireEvent.click(first)
    expect(screen.getByRole('button', { name: 'Mark 1 as checked' })).toBeEnabled()
  })
})
