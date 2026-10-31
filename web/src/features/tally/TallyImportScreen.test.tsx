import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoucherRun } from '@/api/queries/tallyImport'
import { TallyImportScreen } from './TallyImportScreen'

const post = vi.fn()
const get = vi.fn()
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { post: (...args: unknown[]) => post(...args), get: (...args: unknown[]) => get(...args) },
}))

const preview = (over: Partial<VoucherRun['counts']> = {}, rows: VoucherRun['rows'] = []): VoucherRun => ({
  id: 'r1',
  status: 'PREVIEW',
  financial_year: 2025,
  expires_at: '2099-01-01T00:00:00Z',
  result: null,
  created_at: '2025-05-01T10:00:00Z',
  file_name: 'v.xml',
  document: 'd1',
  uploaded_by_name: 'Asha',
  posting: false,
  progress: null,
  error: '',
  counts: { vouchers: 3, will_post: 1, will_make_bill: 1, skipped: 2, bank_waiting: 1, bank_rows: 0, stock_lines: 0, by_type: { Sales: 1, Payment: 1, Journal: 1 }, date_from: '2025-04-01', date_to: '2025-04-03', ...over },
  rows: [
    { ordinal: 2, type: 'Journal', number: '2', date: '2025-04-02', party: '', total_paise: 1000, action: 'skip', bill: false, reason: "The ledger 'Ghost' is not in the client's chart. Import the masters first.", note: '' },
    { ordinal: 3, type: 'Payment', number: '3', date: '2025-04-03', party: '', total_paise: 1000, action: 'skip', bill: false, reason: 'Bank vouchers are imported in a later release.', note: '' },
    ...rows,
  ],
})

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <TallyImportScreen clientId="c1" />
    </QueryClientProvider>,
  )
}

const choose = () => fireEvent.change(screen.getByLabelText('Vouchers file'), { target: { files: [new File(['<x/>'], 'v.xml', { type: 'text/xml' })] } })

describe('TallyImportScreen', () => {
  beforeEach(() => {
    post.mockReset()
    get.mockReset()
    get.mockResolvedValue([])
  })

  it('shows the counts, the bank notice and why each voucher was left out', async () => {
    post.mockResolvedValueOnce(preview())
    renderScreen()
    choose()
    expect(await screen.findByTestId('counts')).toHaveTextContent('3 vouchers from 2025-04-01 to 2025-04-03: 1 will be posted (1 bill made)')
    expect(screen.getByText(/1 bank voucher is left out/)).toBeInTheDocument()
    expect(screen.getByText(/Ghost/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Post 1 voucher/ })).toBeEnabled()
  })

  it('cannot post when nothing would be posted', async () => {
    post.mockResolvedValueOnce(preview({ will_post: 0, will_make_bill: 0, bank_waiting: 0 }))
    renderScreen()
    choose()
    expect(await screen.findByRole('button', { name: /Post 0 vouchers/ })).toBeDisabled()
  })

  it('posts, then shows what was written and what failed', async () => {
    post.mockResolvedValueOnce(preview())
    post.mockResolvedValueOnce({ ...preview(), posting: true, progress: { done: 0, total: 1 } })
    get.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith('/voucher-run/')
          ? { ...preview(), status: 'CONFIRMED', result: { posted: 1, bills: 1, skipped: 0, failed: [{ guid: 'g9', reason: 'The books are signed off through 30-04-2025.' }] } }
          : [],
      ),
    )
    renderScreen()
    choose()
    fireEvent.click(await screen.findByRole('button', { name: /Post 1 voucher/ }))
    expect(await screen.findByRole('progressbar', { name: 'Posting progress' })).toBeInTheDocument()
    expect(await screen.findByText(/1 voucher posted, 1 bill made/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/signed off through 30-04-2025/)).toBeInTheDocument()
    expect(post).toHaveBeenLastCalledWith('/api/v1/clients/c1/tally-imports/r1/confirm-vouchers/', { allow_overlap: false })
  })

  it('asks for the accountant says-so before posting on top of entries already there', async () => {
    post.mockResolvedValueOnce(preview({ existing_entries: 4 }))
    renderScreen()
    choose()
    const button = await screen.findByRole('button', { name: /Post 1 voucher/ })
    expect(screen.getByTestId('overlap')).toHaveTextContent('already has 4 entries')
    expect(button).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Import anyway' }))
    expect(button).toBeEnabled()
  })

  it('lists the imports in the queue, with the stored file to download', async () => {
    get.mockResolvedValue([{ ...preview(), rows: undefined }])
    renderScreen()
    expect(await screen.findByRole('list', { name: 'Imports' })).toHaveTextContent('v.xml')
    expect(screen.getByRole('link', { name: 'Download v.xml' })).toHaveAttribute('href', '/api/v1/documents/d1/download/')
    expect(screen.getByText('Waiting to be posted')).toBeInTheDocument()
  })

  it("shows the server's own words when the file is refused", async () => {
    post.mockRejectedValueOnce(new Error('This client already has entries between 01-04-2025 and 03-04-2025.'))
    renderScreen()
    choose()
    expect(await screen.findByRole('alert')).toHaveTextContent('already has entries')
    await waitFor(() => expect(screen.queryByTestId('counts')).not.toBeInTheDocument())
  })
})
