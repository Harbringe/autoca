import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from '@/lib/toast'
import { StockTallyImportCard } from './StockTallyImportCard'

const post = vi.fn()
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn() } }))

const PREVIEW = {
  applied: false,
  counts: { new: 1, filled: 1, same: 0, opening_added: 1, opening_skipped: 1 },
  rows: [
    { name: 'Mustard Oil 1L', unit: 'Nos', opening_qty: '40', opening_value_paise: 400000, item: 'new', opening: 'add', reason: '' },
    { name: 'Rice', unit: 'Kg', opening_qty: '10', opening_value_paise: 50000, item: 'fill', opening: 'exists', reason: 'This year already has opening stock for this item.' },
  ],
}

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const { container } = render(
    <QueryClientProvider client={queryClient}>
      <StockTallyImportCard clientId="c1" />
    </QueryClientProvider>,
  )
  const choose = () => fireEvent.change(container.querySelector('input[type=file]') as HTMLInputElement, { target: { files: [new File(['<x/>'], 'items.xml')] } })
  return { choose }
}

beforeEach(() => {
  post.mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
})

describe('StockTallyImportCard', () => {
  it('reads the file and shows what would happen, writing nothing', async () => {
    post.mockResolvedValueOnce(PREVIEW)
    const { choose } = setup()
    choose()
    const table = await screen.findByRole('table', { name: 'Stock items found in the file' })
    expect(within(table).getByText('Mustard Oil 1L')).toBeInTheDocument()
    const form = post.mock.calls[0]![1] as FormData
    expect(post.mock.calls[0]![0]).toBe('/api/v1/clients/c1/stock-items/import-tally/')
    expect([form.get('financial_year'), form.get('apply')]).toEqual(['2025', 'false'])
    const rice = within(table).getByText('Rice').closest('tr')!
    expect(within(rice).getByText(/already has opening stock/)).toBeInTheDocument()
  })

  it('writes them when the person says so, with the same file', async () => {
    post.mockResolvedValueOnce(PREVIEW).mockResolvedValueOnce({ ...PREVIEW, applied: true })
    const { choose } = setup()
    choose()
    await userEvent.click(await screen.findByRole('button', { name: /Bring in 2 items/ }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    const form = post.mock.calls[1]![1] as FormData
    expect(form.get('apply')).toBe('true')
    expect((form.get('file') as File).name).toBe('items.xml')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/1 new item/)))
  })

  it('says in words when the file is not a stock item export', async () => {
    post.mockRejectedValueOnce(new Error('This file could not be read as a Tally stock items export.'))
    const { choose } = setup()
    choose()
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('This file could not be read as a Tally stock items export.'))
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
