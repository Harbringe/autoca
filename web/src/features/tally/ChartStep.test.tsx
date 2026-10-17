import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MastersRow, MastersRun } from '@/api/queries/tallyImport'
import { ChartStep } from './ChartStep'

const post = vi.fn()
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { post: (...args: unknown[]) => post(...args), get: vi.fn() },
}))

const row = (over: Partial<MastersRow>): MastersRow => ({
  row: 0, name: 'Rent', tally_group: 'Indirect Expenses', our_group: 'INDIRECT_EXPENSE', opening_paise: 0, opening_display: '₹0.00',
  action: 'create', reason: '', ledger_name: null, conflict: null, bank: null, ...over,
})

const run = (rows: MastersRow[], over: Partial<MastersRun> = {}): MastersRun => ({
  id: 'm1', status: 'PREVIEW', financial_year: 2025, result: null, rows,
  counts: { create: 1, match: 0, conflict: 1, needs_group: 0, skipped: 0, with_opening: 0, bank_conflicts: 0, difference_display: '₹0.00' },
  ...over,
})

function renderStep() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <ChartStep clientId="c1" />
    </QueryClientProvider>,
  )
}

const choose = () => fireEvent.change(screen.getByLabelText('Ledgers file'), { target: { files: [new File(['<x/>'], 'm.xml', { type: 'text/xml' })] } })

describe('ChartStep', () => {
  beforeEach(() => {
    post.mockReset()
  })

  it('will not apply until every line that needs a choice has one, and assumes nothing', async () => {
    const conflict = row({ row: 1, name: 'Sundry Cash', action: 'conflict', conflict: { kind: 'group_differs', choices: ['keep_ours', 'take_tally', 'skip'], default: null } })
    post.mockResolvedValueOnce(run([row({}), conflict]))
    renderStep()
    choose()
    expect(await screen.findByTestId('chart-counts')).toHaveTextContent('1 new')
    const apply = screen.getByRole('button', { name: /Apply the ledgers/ })
    expect(apply).toBeDisabled()
    expect(screen.getByText(/1 line still need your choice/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('What to do with Sundry Cash'), { target: { value: 'keep_ours' } })
    expect(apply).toBeEnabled()
  })

  it('sends the chosen year and the choices, then reports what was added', async () => {
    const conflict = row({ row: 1, name: 'Sundry Cash', action: 'conflict', conflict: { kind: 'group_differs', choices: ['keep_ours', 'skip'], default: 'keep_ours' } })
    post.mockResolvedValueOnce(run([conflict]))
    post.mockResolvedValueOnce(
      run([conflict], { status: 'CONFIRMED', result: { created: 4, matched: 2, renamed: 0, regrouped: 0, openings: 3, bank_openings: 0, skipped: 0, difference_display: '₹0.00' } }),
    )
    renderStep()
    fireEvent.change(screen.getByLabelText('Year the balances are as at'), { target: { value: '2024' } })
    choose()
    fireEvent.click(await screen.findByRole('button', { name: /Apply the ledgers/ }))
    expect(await screen.findByText(/4 ledgers added, 2 already there, 3 opening balances stored/)).toBeInTheDocument()
    const upload = post.mock.calls[0]![1] as FormData
    expect(upload.get('financial_year')).toBe('2024')
    expect(post).toHaveBeenLastCalledWith('/api/v1/clients/c1/tally-imports/m1/confirm/', { resolutions: [{ row: 1, choice: 'keep_ours' }] })
  })

  it("shows the server's words when the file is refused", async () => {
    post.mockRejectedValueOnce(new Error("This file's balances are as at 01-04-2019."))
    renderStep()
    choose()
    expect(await screen.findByRole('alert')).toHaveTextContent('balances are as at')
  })
})
