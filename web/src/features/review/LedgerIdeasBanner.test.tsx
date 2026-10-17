import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Classification } from '@/api/types'
import { LedgerIdeasBanner } from './LedgerIdeasBanner'

const post = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn() } }))

let n = 0
const idea = (name: string, existing: string | null = null) => ({ name, group: 'INDIRECT_EXPENSE', group_display: 'Indirect expenses', existing_ledger: existing, existing_name: existing ? name : null, rows_sharing: 0 })
const row = (suggestion: ReturnType<typeof idea>, over: Record<string, unknown> = {}): Classification => {
  n += 1
  return { id: `r${n}`, ledger: null, is_posted: false, is_self_transfer: false, method: 'UNRESOLVED', counterparty: `Payee ${n}`, suggested_ledger: suggestion, transaction: { value_date: '2026-04-01', amount_display: `₹${n}00.00`, narration: `UPI ${n}` }, rationale: '', ...over } as unknown as Classification
}

function setup(rows: Classification[], canCreate = true) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LedgerIdeasBanner clientId="c1" rows={rows} canPlace canCreate={canCreate} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  n = 0
  post.mockReset()
  post.mockImplementation(async (url: string) => (url.endsWith('/ledgers/') ? { id: 'new-ledger' } : { classification: {} }))
})

describe('using the assistant’s ledger ideas all at once', () => {
  it('says how many rows have an idea and how many ledgers it would open, and shows nothing when there are none', () => {
    setup([row(idea('Fuel')), row(idea('Fuel')), row(idea('Telephone', 'l9'))])
    expect(screen.getByText(/ledger idea for/)).toHaveTextContent('3 rows')
    expect(screen.getByText(/1 new ledger to open/)).toBeInTheDocument()
  })

  it('opens each new ledger once and places every row that carries its idea, a few at a time', async () => {
    const user = userEvent.setup()
    setup([row(idea('Fuel')), row(idea('Fuel')), row(idea('Fuel')), row(idea('Telephone', 'l9'))])
    await user.click(screen.getByRole('button', { name: /Use all 4 ideas/ }))
    const dialog = await screen.findByRole('dialog')
    expect(post).not.toHaveBeenCalled()
    expect(within(dialog).getByText('Fuel')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Place 4' }))
    await waitFor(() => expect(post.mock.calls.filter((c) => String(c[0]).includes('/review/')).length).toBe(4))
    const created = post.mock.calls.filter((c) => String(c[0]).endsWith('/ledgers/'))
    expect(created).toHaveLength(1)
    expect(created[0]![1]).toEqual({ name: 'Fuel', group: 'INDIRECT_EXPENSE' })
    const placements = post.mock.calls.filter((c) => String(c[0]).includes('/review/')).map((c) => c[1] as { ledger: string; learn: boolean })
    expect(placements.filter((p) => p.ledger === 'new-ledger')).toHaveLength(3)
    expect(placements.filter((p) => p.ledger === 'l9')).toHaveLength(1)
    // a row with a payee teaches its rule, as placing it by hand does
    expect(placements.every((p) => p.learn)).toBe(true)
  })

  it('shows which rows go to which ledger before anything is placed, and leaves out an idea that is unticked', async () => {
    const user = userEvent.setup()
    setup([row(idea('Fuel')), row(idea('Fuel')), row(idea('Telephone', 'l9'))])
    await user.click(screen.getByRole('button', { name: /Use all 3 ideas/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Payee 1')).toBeInTheDocument()
    expect(within(dialog).getByText('Payee 3')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('checkbox', { name: 'Use the idea Fuel' }))
    await user.click(within(dialog).getByRole('button', { name: 'Place 1' }))
    await waitFor(() => expect(post.mock.calls.filter((c) => String(c[0]).includes('/review/'))).toHaveLength(1))
    expect(post.mock.calls.some((c) => String(c[0]).endsWith('/ledgers/'))).toBe(false)
  })

  it('leaves the ideas that need a new ledger when the person may not open ledgers', async () => {
    const user = userEvent.setup()
    setup([row(idea('Fuel')), row(idea('Telephone', 'l9'))], false)
    await user.click(screen.getByRole('button', { name: /Use all 1 idea/ }))
    await user.click(await screen.findByRole('button', { name: 'Place 1' }))
    await waitFor(() => expect(post.mock.calls.filter((c) => String(c[0]).includes('/review/'))).toHaveLength(1))
    expect(post.mock.calls.some((c) => String(c[0]).endsWith('/ledgers/'))).toBe(false)
  })
})
