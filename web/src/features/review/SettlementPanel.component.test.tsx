import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { rowSettlement } from '@/api/queries/bills'
import type { Classification, SettlementContext } from '@/api/types'
import { SettlementPanel } from './SettlementPanel'

const post = vi.fn()
vi.mock('@/api/client', () => ({ raw: { post: (...args: unknown[]) => post(...args), get: vi.fn() } }))

const CLIENT = 'c1'
const ROW = { id: 'r1', party_name: 'Ravi Traders' } as unknown as Classification

function context(over: Partial<SettlementContext> = {}): SettlementContext {
  return {
    party: { id: 'p1', name: 'Ravi Traders' },
    amount_paise: 12_000_00,
    amount_display: '₹12,000.00',
    direction: 'DR',
    already_allocated_paise: 0,
    bills: [
      { id: 'b1', kind: 'PURCHASE', kind_display: 'Purchase invoice', reference: 'INV-1', bill_date: '2025-04-01', due_date: null, total_paise: 10_000_00, total_display: '₹10,000.00', open_paise: 10_000_00, open_display: '₹10,000.00' },
      { id: 'b2', kind: 'PURCHASE', kind_display: 'Purchase invoice', reference: 'INV-2', bill_date: '2025-05-01', due_date: null, total_paise: 5_000_00, total_display: '₹5,000.00', open_paise: 5_000_00, open_display: '₹5,000.00' },
    ],
    proposal: {
      allocations: [{ bill: 'b1', amount_paise: 10_000_00, amount_display: '₹10,000.00' }, { bill: 'b2', amount_paise: 2_000_00, amount_display: '₹2,000.00' }],
      remainder_paise: 0,
      remainder_display: '₹0.00',
      basis: 'oldest_first',
    },
    ...over,
  } as unknown as SettlementContext
}

function renderPanel(ctx: SettlementContext = context(), onDone = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(rowSettlement(CLIENT, ROW.id).queryKey, ctx)
  render(
    <QueryClientProvider client={queryClient}>
      <SettlementPanel clientId={CLIENT} row={ROW} onDone={onDone} />
    </QueryClientProvider>,
  )
  return onDone
}

describe('Settling a payment on a party’s account', () => {
  it('is prefilled from the suggestion, and says it is only a suggestion', async () => {
    renderPanel()
    expect(await screen.findByLabelText('Settle against INV-1')).toHaveValue('10000.00')
    expect(screen.getByLabelText('Settle against INV-2')).toHaveValue('2000.00')
    expect(screen.getByText(/Suggested:/)).toHaveTextContent('oldest bills first')
    expect(screen.getByText(/nothing is posted until you do/)).toBeInTheDocument()
  })

  it('says how much is settled and posts exactly what the person confirms', async () => {
    post.mockResolvedValue([])
    const onDone = renderPanel()
    await screen.findByLabelText('Settle against INV-1')
    await userEvent.click(screen.getByRole('button', { name: 'Post and settle' }))

    expect(post).toHaveBeenCalledWith('/api/v1/clients/c1/approvals/', {
      classifications: ['r1'],
      settlements: [{ classification: 'r1', remainder: null, allocations: [{ bill: 'b1', amount_paise: 10_000_00 }, { bill: 'b2', amount_paise: 2_000_00 }] }],
    })
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('lets the person change the amounts and hold what is left on account or as an advance', async () => {
    post.mockResolvedValue([])
    renderPanel()
    const second = await screen.findByLabelText('Settle against INV-2')
    await userEvent.clear(second)
    await userEvent.type(second, '500')
    expect(screen.getByText(/left over/)).toHaveTextContent('₹1,500.00')

    await userEvent.selectOptions(screen.getByLabelText('What to do with the rest'), 'ADVANCE')
    await userEvent.click(screen.getByRole('button', { name: 'Post and settle' }))

    const body = post.mock.calls.at(-1)![1] as { settlements: { remainder: string; allocations: { bill: string; amount_paise: number }[] }[] }
    expect(body.settlements[0]!.remainder).toBe('ADVANCE')
    expect(body.settlements[0]!.allocations).toEqual([{ bill: 'b1', amount_paise: 10_000_00 }, { bill: 'b2', amount_paise: 500_00 }])
  })

  it('refuses amounts that are more than moved, or more than is open, and disables posting', async () => {
    renderPanel()
    const second = await screen.findByLabelText('Settle against INV-2')
    await userEvent.clear(second)
    await userEvent.type(second, '9000')
    expect(within(screen.getByRole('region', { name: /Settle Ravi Traders/ })).getByText(/Only ₹5,000.00 of this bill/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Post and settle' })).toBeDisabled()

    await userEvent.clear(second)
    await userEvent.type(second, '5000')
    expect(screen.getByRole('alert')).toHaveTextContent('more than the')
    expect(screen.getByRole('button', { name: 'Post and settle' })).toBeDisabled()
  })

  it('with no open bills, everything is held and can still be posted', async () => {
    renderPanel(
      context({
        bills: [],
        proposal: { allocations: [], remainder_paise: 12_000_00, remainder_display: '₹12,000.00', basis: 'none' } as SettlementContext['proposal'],
      }),
    )
    expect(await screen.findByText(/has no open bills on this side/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Post and settle' })).toBeEnabled()
  })

  it('says it was a receipt when the money came in', async () => {
    renderPanel(context({ direction: 'CR' }))
    expect(await screen.findByText(/Received/)).toBeInTheDocument()
  })
})
