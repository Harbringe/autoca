import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LedgerAccount } from '@/api/types'
import { setAllPageSize } from '@/lib/pageSizes'
import { ProposedLedgers } from './ProposedLedgers'

const post = vi.fn()
const get = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: (...a: unknown[]) => get(...a) } }))

const ledger = (i: number, over: Partial<LedgerAccount> = {}) =>
  ({ id: `l${i}`, name: `Ledger ${String(i).padStart(2, '0')}`, group: 'INDIRECT_EXPENSE', proposal_reason: 'idea', row_count: i, status: 'ACTIVE', ...over }) as LedgerAccount

function setup(n: number, mayDecide = true) {
  const onDecide = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ProposedLedgers clientId="c1" proposed={Array.from({ length: n }, (_, i) => ledger(i + 1))} mayDecide={mayDecide} onDecide={onDecide} />
    </QueryClientProvider>,
  )
  return { onDecide }
}

beforeEach(() => {
  setAllPageSize(10)
  post.mockReset()
  get.mockReset()
  post.mockResolvedValue({})
})

describe('the ledgers the assistant added', () => {
  it('shows the rows a ledger holds before it is kept, and the group select is wide enough for its words', async () => {
    const user = userEvent.setup()
    get.mockResolvedValue({ count: 1, next: null, previous: null, results: [{ id: 'r1', value_date: '2026-04-01', counterparty: 'Mauli Traders', narration: 'UPI/123', amount_display: '₹500.00', is_debit: false, is_posted: false }] })
    setup(2)
    await user.click(screen.getByRole('button', { name: 'Preview the rows in Ledger 01' }))
    expect(await screen.findByText('Mauli Traders')).toBeInTheDocument()
    expect(screen.getByText(/Rows in Ledger 01/)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Group for the selected ledgers' })).toHaveClass('w-72')
  })

  it('are paged ten at a time', () => {
    setup(23)
    expect(screen.getByText('Ledger 01')).toBeInTheDocument()
    expect(screen.queryByText('Ledger 11')).toBeNull()
    expect(screen.getByText(/Showing 1–10 of 23/)).toBeInTheDocument()
  })

  it('can all be selected at once, across pages, and kept with one confirmation', async () => {
    const user = userEvent.setup()
    setup(12)
    await user.click(screen.getByRole('checkbox', { name: 'Select all 12' }))
    expect(screen.getByText('12 selected')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Keep 12 ledgers' }))
    const dialog = await screen.findByRole('dialog')
    expect(post).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Keep 12' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(12))
    expect(post.mock.calls[0]![0]).toContain('/ledgers/l1/accept/')
    // each is kept with the name and group it already has
    expect(post.mock.calls[0]![1]).toEqual({ name: 'Ledger 01', group: 'INDIRECT_EXPENSE' })
  })

  it('can be kept in one group chosen for all of the selected', async () => {
    const user = userEvent.setup()
    setup(2)
    await user.click(screen.getByRole('checkbox', { name: 'Select all 2' }))
    await user.selectOptions(screen.getByLabelText('Group for the selected ledgers'), 'DIRECT_EXPENSE')
    await user.click(screen.getByRole('button', { name: 'Keep 2 ledgers' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Keep 2' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    expect(post.mock.calls.every((c) => (c[1] as { group: string }).group === 'DIRECT_EXPENSE')).toBe(true)
  })

  it('offers no selecting or keeping to someone who may not decide', () => {
    setup(3, false)
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('button', { name: /Keep/ })).toBeNull()
  })
})
