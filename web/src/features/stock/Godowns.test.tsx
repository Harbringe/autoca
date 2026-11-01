import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { godowns, type Godown } from '@/api/queries/godowns'
import { stockItems, type StockItem } from '@/api/queries/stockItems'
import { toast } from '@/lib/toast'
import { GodownsCard } from './GodownsCard'
import { StockCountCard } from './StockCountCard'
import { StockMoveCard } from './StockMoveCard'

const post = vi.fn()
const del = vi.fn()
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/api/client', async (orig) => ({
  ...(await orig<object>()),
  raw: { post: (...a: unknown[]) => post(...a), delete: (...a: unknown[]) => del(...a), get: vi.fn(), patch: vi.fn() },
}))

const GODOWNS: Godown[] = [
  { id: 'g1', name: 'Shop' },
  { id: 'g2', name: 'Yard' },
]
const ITEMS = [{ id: 'i1', name: 'Mustard Oil 1L', unit: 'Nos' }] as unknown as StockItem[]

function wrap(ui: React.ReactNode, list: Godown[] = GODOWNS) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } })
  queryClient.setQueryData(godowns('c1').queryKey, list)
  queryClient.setQueryData(stockItems('c1').queryKey, ITEMS)
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  post.mockReset()
  del.mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
})

describe('GodownsCard', () => {
  it('lists the godowns and adds one', async () => {
    post.mockResolvedValueOnce({ id: 'g3', name: 'Godown 3' })
    wrap(<GodownsCard clientId="c1" mayEdit />)
    expect(within(screen.getByRole('list', { name: 'Godowns' })).getByText('Shop')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Godown name'), 'Godown 3')
    await userEvent.click(screen.getByRole('button', { name: 'Add godown' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/clients/c1/godowns/', { name: 'Godown 3' }))
  })

  it('removes one', async () => {
    del.mockResolvedValueOnce(undefined)
    wrap(<GodownsCard clientId="c1" mayEdit />)
    await userEvent.click(screen.getByRole('button', { name: 'Remove Yard' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/v1/clients/c1/godowns/g2/'))
  })

  it('shows the list but no controls to a person who may not edit', () => {
    wrap(<GodownsCard clientId="c1" mayEdit={false} />)
    expect(screen.getByText('Shop')).toBeInTheDocument()
    expect(screen.queryByLabelText('Godown name')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })
})

describe('StockMoveCard', () => {
  it('moves stock from the main location to a godown', async () => {
    post.mockResolvedValueOnce({ entries: [] })
    wrap(<StockMoveCard clientId="c1" />)
    await userEvent.type(screen.getByLabelText('Item to move'), 'Mustard Oil 1L')
    await userEvent.type(screen.getByLabelText('Quantity to move'), '30')
    await userEvent.selectOptions(screen.getByLabelText('Move from'), 'Main location')
    await userEvent.selectOptions(screen.getByLabelText('Move to'), 'Yard')
    await userEvent.click(screen.getByRole('button', { name: 'Move stock' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        '/api/v1/clients/c1/stock-entries/transfer/',
        expect.objectContaining({ name: 'Mustard Oil 1L', quantity: '30', from_godown: null, to_godown: 'g2' }),
      ),
    )
  })

  it('will not move stock from a place to the same place', async () => {
    wrap(<StockMoveCard clientId="c1" />)
    await userEvent.type(screen.getByLabelText('Item to move'), 'Mustard Oil 1L')
    await userEvent.type(screen.getByLabelText('Quantity to move'), '3')
    await userEvent.selectOptions(screen.getByLabelText('Move from'), 'Shop')
    await userEvent.selectOptions(screen.getByLabelText('Move to'), 'Shop')
    expect(screen.getByRole('button', { name: 'Move stock' })).toBeDisabled()
  })
})

describe('StockCountCard', () => {
  it('books a count and says what it found', async () => {
    post.mockResolvedValueOnce({ book_quantity: '100', counted_quantity: '96', difference: '-4', entry: { id: 'e1' } })
    wrap(<StockCountCard clientId="c1" />)
    await userEvent.type(screen.getByLabelText('Item counted'), 'Mustard Oil 1L')
    await userEvent.type(screen.getByLabelText('Counted quantity'), '96')
    await userEvent.click(screen.getByRole('button', { name: 'Record count' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        '/api/v1/clients/c1/stock-entries/count/',
        expect.objectContaining({ name: 'Mustard Oil 1L', counted_quantity: '96' }),
      ),
    )
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/4 short.*stock out/)))
  })

  it('says when the count agrees with the books', async () => {
    post.mockResolvedValueOnce({ book_quantity: '100', counted_quantity: '100', difference: '0', entry: null })
    wrap(<StockCountCard clientId="c1" />)
    await userEvent.type(screen.getByLabelText('Item counted'), 'Mustard Oil 1L')
    await userEvent.type(screen.getByLabelText('Counted quantity'), '100')
    await userEvent.click(screen.getByRole('button', { name: 'Record count' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/agrees with the books/)))
  })
})
