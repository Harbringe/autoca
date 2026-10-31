import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TrialBalanceCheck } from './TrialBalanceCheck'

const post = vi.fn()
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { post: (...args: unknown[]) => post(...args), get: vi.fn() },
}))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))

function renderCheck() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <TrialBalanceCheck clientId="c1" />
    </QueryClientProvider>,
  )
}

const choose = () => fireEvent.change(screen.getByLabelText('Trial balance file'), { target: { files: [new File(['{}'], 'tb.json', { type: 'application/json' })] } })

describe('TrialBalanceCheck', () => {
  beforeEach(() => post.mockReset())

  it('lists each ledger whose closing balance differs, with both figures', async () => {
    post.mockResolvedValueOnce({ matched: 12, differences: [{ name: 'Rent', tally_paise: 90000, ours_paise: -100000 }] })
    renderCheck()
    choose()
    expect(await screen.findByText('Rent')).toBeInTheDocument()
    expect(screen.getByTestId('tb-matched')).toHaveTextContent('12 ledgers agree')
    expect(screen.getByText('₹900.00')).toBeInTheDocument()
    expect(post).toHaveBeenLastCalledWith('/api/v1/clients/c1/tally-imports/check-trial-balance/', expect.any(FormData))
  })

  it('says everything matches when nothing differs', async () => {
    post.mockResolvedValueOnce({ matched: 40, differences: [] })
    renderCheck()
    choose()
    expect(await screen.findByText(/Everything matches/)).toBeInTheDocument()
  })

  it("shows the server's words when the file is refused", async () => {
    post.mockRejectedValueOnce(new Error('This file could not be read as a Tally trial balance.'))
    renderCheck()
    choose()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('could not be read'))
  })
})
