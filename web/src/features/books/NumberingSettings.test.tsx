import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NumberingSettings } from './NumberingSettings'

const get = vi.fn()
const put = vi.fn()
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { get: (...args: unknown[]) => get(...args), put: (...args: unknown[]) => put(...args), post: vi.fn() },
}))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))

const series = [
  { voucher_type: 'Sales', type_name: '', prefix: '', padding: 0, example: '1' },
  { voucher_type: 'Sales', type_name: 'GST SALE', prefix: 'G', padding: 2, example: 'G01' },
  { voucher_type: 'Purchase', type_name: '', prefix: '', padding: 0, example: '1' },
]

function renderCard(mayEdit = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <NumberingSettings clientId="c1" mayEdit={mayEdit} />
    </QueryClientProvider>,
  )
}

describe('NumberingSettings', () => {
  beforeEach(() => {
    get.mockReset()
    put.mockReset()
    get.mockResolvedValue(series)
  })

  it('lists every series with the number it will give next', async () => {
    renderCard()
    expect(await screen.findByText('GST SALE')).toBeInTheDocument()
    expect(screen.getByTestId('example-Sales-')).toHaveTextContent('1')
    expect(screen.getByTestId('example-Sales-GST SALE')).toHaveTextContent('G01')
    expect(get).toHaveBeenCalledWith('/api/v1/clients/c1/numbering/?fy=2025')
  })

  it('saves only the series that were changed', async () => {
    put.mockResolvedValue(series)
    renderCard()
    fireEvent.change(await screen.findByLabelText('Prefix for Purchase'), { target: { value: 'P/{fy}/' } })
    fireEvent.change(screen.getByLabelText('Digits for Purchase'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save number formats' }))
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith('/api/v1/clients/c1/numbering/?fy=2025', [{ voucher_type: 'Purchase', type_name: '', prefix: 'P/{fy}/', padding: 4 }]),
    )
  })

  it('cannot be changed by someone who may not edit', async () => {
    renderCard(false)
    expect(await screen.findByText('GST SALE')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save number formats' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Prefix for Purchase')).toBeDisabled()
  })
})
