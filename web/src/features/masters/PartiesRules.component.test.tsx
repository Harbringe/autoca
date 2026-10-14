import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { parties, rules } from '@/api/queries/books'
import { partyCandidates } from '@/api/queries/bills'
import type { Party, Rule } from '@/api/types'
import { MastersScreen } from './MastersScreen'

vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

const party = (over: Partial<Party>): Party =>
  ({ id: 'p1', canonical_name: 'Shree Ganesh Steel Traders', role: 'VENDOR', role_display: 'Supplier', gstin: '27ABCDE1234F1Z5', tds_section: '194C', rcm_default: false, msme: true, is_active: true, ...over }) as Party

const rule = (over: Partial<Rule>): Rule =>
  ({ id: 'r1', match_type: 'PARTY_EQUALS', pattern: 'Shree Ganesh Steel Traders', direction: 'DEBIT', ledger_name: 'Purchases', party: 'p1', source: 'LEARNED', hit_count: 3, last_hit_at: null, is_active: true, priority: 0, ...over }) as Rule

function renderTab(tab: 'parties' | 'rules', ps: Party[], rs: Rule[], found: unknown[] = []) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(parties('c1').queryKey, ps)
  queryClient.setQueryData(rules('c1').queryKey, rs)
  queryClient.setQueryData(partyCandidates('c1', false).queryKey, { candidates: found } as never)
  render(
    <QueryClientProvider client={queryClient}>
      <MastersScreen clientId="c1" tab={tab} />
    </QueryClientProvider>,
  )
}

describe('parties, as a directory', () => {
  const ps = [party({}), party({ id: 'p2', canonical_name: 'Patil Constructions', role: 'CUSTOMER', role_display: 'Customer', gstin: '', tds_section: '', msme: false })]

  it('lists each party with its GSTIN, tax defaults and how many rules it has', async () => {
    renderTab('parties', ps, [rule({})])
    expect(await screen.findByText('Shree Ganesh Steel Traders')).toBeInTheDocument()
    expect(screen.getByText('27ABCDE1234F1Z5')).toBeInTheDocument()
    expect(screen.getByText('TDS 194C')).toBeInTheDocument()
    expect(screen.getByText('MSME')).toBeInTheDocument()
    expect(screen.getByText('No GSTIN')).toBeInTheDocument()
    const row = screen.getByText('Shree Ganesh Steel Traders').closest('tr')!
    expect(within(row).getByText('1')).toBeInTheDocument()
  })

  it('opens the form and that payee’s rules under the row, and closes it again', async () => {
    renderTab('parties', ps, [rule({})])
    fireEvent.click(await screen.findByRole('button', { name: 'Edit Shree Ganesh Steel Traders' }))
    expect(screen.getByLabelText('Name')).toHaveValue('Shree Ganesh Steel Traders')
    expect(screen.getByText('Rules for this payee')).toBeInTheDocument()
    expect(screen.getByText('used 3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close Shree Ganesh Steel Traders' }))
    // It folds away with a short animation, then leaves the page.
    await waitFor(() => expect(screen.queryByText('Rules for this payee')).toBeNull())
  })

  it('filters by role', async () => {
    renderTab('parties', ps, [])
    await screen.findByText('Patil Constructions')
    fireEvent.click(screen.getByRole('button', { name: 'Customers' }))
    expect(screen.queryByText('Shree Ganesh Steel Traders')).toBeNull()
    expect(screen.getByText('Patil Constructions')).toBeInTheDocument()
  })

  it('keeps the empty state when there are no parties', async () => {
    renderTab('parties', [], [])
    expect(await screen.findByText('No parties yet')).toBeInTheDocument()
  })
})

describe('rules, as sentences', () => {
  it('reads each rule as one sentence with its source, use and a switch', async () => {
    renderTab('rules', [party({})], [rule({ last_hit_at: '2025-05-14T10:00:00Z' })])
    expect(await screen.findByText('Purchases')).toBeInTheDocument()
    expect(screen.getByText(/Payee is/)).toBeInTheDocument()
    expect(screen.getByText(/money out/)).toBeInTheDocument()
    expect(screen.getByText(/Learned/)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /Active: Payee is Shree Ganesh Steel Traders/ })).toBeChecked()
  })
})

describe('parties found in the statements, on the Parties page', () => {
  const candidate = { name: 'Kirti Oil Industries', count: 6, first: '2025-04-07', last: '2025-05-25', paid_paise: 100, received_paise: 0, paid_display: '₹1.00', received_display: '', suggested_role: 'VENDOR' }

  it('lists who the statements name, to be ticked into real parties', async () => {
    renderTab('parties', [], [], [candidate])
    expect(await screen.findByText('Parties found in these statements')).toBeInTheDocument()
    expect(screen.getByText('Kirti Oil Industries')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Create 0 parties/ })).toBeDisabled()
  })

  it('says nothing when the statements name nobody new', async () => {
    renderTab('parties', [party({})], [], [])
    await screen.findByText('Shree Ganesh Steel Traders')
    expect(screen.queryByText('Parties found in these statements')).toBeNull()
  })
})

describe('paging the parties and the rules', () => {
  const many = <T,>(n: number, make: (i: number) => T) => Array.from({ length: n }, (_, i) => make(i + 1))

  it('shows ten parties a page and turns to the rest', async () => {
    renderTab('parties', many(23, (i) => party({ id: `p${i}`, canonical_name: `Party ${String(i).padStart(2, '0')}` })), [])
    expect(await screen.findByText('Party 01')).toBeInTheDocument()
    expect(screen.queryByText('Party 11')).toBeNull()
    expect(screen.getByText(/Showing 1–10 of 23/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(await screen.findByText('Party 11')).toBeInTheDocument()
    expect(screen.queryByText('Party 01')).toBeNull()
  })

  it('shows ten rules a page', async () => {
    renderTab('rules', [], many(12, (i) => rule({ id: `r${i}`, pattern: `Payee ${i}`, party: null as never, priority: 100 - i })))
    expect(await screen.findByText(/Showing 1–10 of 12/)).toBeInTheDocument()
    expect(screen.getAllByRole('switch')).toHaveLength(10)
  })
})
