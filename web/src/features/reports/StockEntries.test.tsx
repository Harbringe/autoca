import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { godowns } from '@/api/queries/godowns'
import { StockEntries } from './StockEntries'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function setup(places: { id: string; name: string }[]) {
  vi.mocked(raw.get).mockResolvedValue({ results: [] })
  vi.mocked(raw.post).mockResolvedValue({})
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  queryClient.setQueryData(godowns('c1').queryKey, places)
  render(
    <QueryClientProvider client={queryClient}>
      <StockEntries clientId="c1" fy={2025} onClose={() => undefined} />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('StockEntries', () => {
  it('records opening stock in the godown that was picked', async () => {
    setup([{ id: 'g1', name: 'Shop' }])
    await userEvent.type(screen.getByLabelText('Item'), 'Rice')
    await userEvent.type(screen.getByLabelText('Quantity'), '10')
    await userEvent.selectOptions(screen.getByLabelText('Where is it'), 'Shop')
    await userEvent.click(screen.getByRole('button', { name: 'Record' }))
    await waitFor(() =>
      expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/stock-entries/', expect.objectContaining({ name: 'Rice', quantity: '10', godown: 'g1' })),
    )
  })

  it('offers no place to pick when the client has no godowns', () => {
    setup([])
    expect(screen.queryByLabelText('Where is it')).not.toBeInTheDocument()
  })
})
