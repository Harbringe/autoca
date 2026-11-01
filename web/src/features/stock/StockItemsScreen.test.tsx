import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/errors'
import { toast } from '@/lib/toast'
import { stockItems, type StockItem } from '@/api/queries/stockItems'
import { StockItemsScreen } from './StockItemsScreen'

const post = vi.fn()
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const patch = vi.fn()
const del = vi.fn()
vi.mock('@/api/client', async (orig) => ({
  ...(await orig<object>()),
  raw: { post: (...a: unknown[]) => post(...a), patch: (...a: unknown[]) => patch(...a), delete: (...a: unknown[]) => del(...a), get: vi.fn() },
}))

const ITEMS: StockItem[] = [
  { id: 'i1', name: 'Mustard Oil 1L', unit: 'Nos', hsn_sac: '1514', gst_rate: '5.00', reorder_level: '20.000', purchase_ledger: null, purchase_ledger_name: '', sales_ledger: null, sales_ledger_name: '' },
]

function setup(mayEdit = true, items: StockItem[] = ITEMS) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } })
  queryClient.setQueryData(stockItems('c1').queryKey, items)
  render(
    <QueryClientProvider client={queryClient}>
      <StockItemsScreen clientId="c1" mayEdit={mayEdit} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  post.mockReset()
  patch.mockReset()
  del.mockReset()
})

describe('StockItemsScreen', () => {
  it('lists each item with its unit, HSN, GST rate and reorder level', () => {
    setup()
    const row = within(screen.getByRole('row', { name: /Mustard Oil 1L/ }))
    expect(row.getByText('Nos')).toBeInTheDocument()
    expect(row.getByText('1514')).toBeInTheDocument()
    expect(row.getByText('5%')).toBeInTheDocument()
    expect(row.getByText('20')).toBeInTheDocument()
  })

  it('says so when there are no items yet', () => {
    setup(true, [])
    expect(screen.getByText(/No stock items yet/)).toBeInTheDocument()
  })

  it('adds an item', async () => {
    post.mockResolvedValueOnce({ ...ITEMS[0], id: 'i2', name: 'Rice 25kg' })
    setup()
    await userEvent.type(screen.getByLabelText('Item name'), 'Rice 25kg')
    await userEvent.type(screen.getByLabelText('Unit'), 'Bag')
    await userEvent.type(screen.getByLabelText('GST %'), '5')
    await userEvent.click(screen.getByRole('button', { name: 'Add item' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/clients/c1/stock-items/', { name: 'Rice 25kg', unit: 'Bag', gst_rate: '5' }),
    )
  })

  it('says what the server found wrong with a field, not just that something is invalid', async () => {
    post.mockRejectedValueOnce(
      new ApiError(400, { detail: 'Some fields are invalid.', code: 'validation_error', fields: { name: ['This client already has an item with that name.'] } }),
    )
    setup()
    await userEvent.type(screen.getByLabelText('Item name'), 'mustard oil 1l')
    await userEvent.click(screen.getByRole('button', { name: 'Add item' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('This client already has an item with that name.'))
  })

  it('changes the reorder level', async () => {
    patch.mockResolvedValueOnce({ ...ITEMS[0], reorder_level: '35.000' })
    setup()
    await userEvent.click(screen.getByRole('button', { name: 'Edit Mustard Oil 1L' }))
    const level = screen.getByLabelText('Reorder level of Mustard Oil 1L')
    await userEvent.clear(level)
    await userEvent.type(level, '35')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/api/v1/clients/c1/stock-items/i1/', expect.objectContaining({ reorder_level: '35' })))
  })

  it('removes an item after asking', async () => {
    del.mockResolvedValueOnce(undefined)
    setup()
    await userEvent.click(screen.getByRole('button', { name: 'Remove Mustard Oil 1L' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Remove item' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/v1/clients/c1/stock-items/i1/'))
  })

  it('shows the list but no controls to a person who may not edit', () => {
    setup(false)
    expect(screen.getByText('Mustard Oil 1L')).toBeInTheDocument()
    expect(screen.queryByLabelText('Item name')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit|Remove/ })).not.toBeInTheDocument()
  })
})
