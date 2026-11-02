import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { ManufacturingCard } from './ManufacturingCard'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const BOM = { id: 'b1', name: 'Masala Mix', unit: 'pkt', output_quantity: '10.000', components: [{ name: 'Chilli', unit: 'kg', quantity: '2.000' }, { name: 'Salt', unit: 'kg', quantity: '1.500' }] }
const OK = { quantity: '20', components: [{ name: 'Chilli', unit: 'kg', needed: '4', available: '100', cost_paise: 80000, enough: true }], cost_paise: 86000, short: [] }
const SHORT = { quantity: '1000', components: [{ name: 'Chilli', unit: 'kg', needed: '200', available: '100', cost_paise: 4000000, enough: false }], cost_paise: 4000000, short: ['Chilli: needs 200, has 100'] }

function show(plan: object = OK) {
  vi.mocked(raw.get).mockImplementation(((url: string) => Promise.resolve(url.includes('/plan/') ? plan : { results: [BOM], next: null, count: 1 })) as never)
  vi.mocked(raw.post).mockResolvedValue({})
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ManufacturingCard clientId="c1" mayEdit />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('ManufacturingCard', () => {
  it('shows what is needed and what it costs for a quantity, and runs production', async () => {
    show()
    await userEvent.type(await screen.findByLabelText('Quantity of Masala Mix to make'), '20')
    expect(await screen.findByText(/Chilli: needs 4 kg, has 100/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Extra cost for Masala Mix'), '500')
    await userEvent.click(screen.getByRole('button', { name: 'Run production' }))
    await waitFor(() =>
      expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/boms/b1/produce/', expect.objectContaining({ quantity: '20', extra_cost_paise: 50000 })),
    )
  })

  it('names a short component and will not run', async () => {
    show(SHORT)
    await userEvent.type(await screen.findByLabelText('Quantity of Masala Mix to make'), '1000')
    expect(await screen.findByText(/— short/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run production' })).toBeDisabled()
  })

  it('saves a new bill of materials', async () => {
    show()
    await userEvent.type(await screen.findByLabelText('Finished item'), 'Spice Box')
    await userEvent.type(screen.getByLabelText('Component 1 name'), 'Cumin')
    await userEvent.type(screen.getByLabelText('Component 1 quantity'), '3')
    await userEvent.click(screen.getByRole('button', { name: 'Save bill of materials' }))
    await waitFor(() =>
      expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/boms/', expect.objectContaining({ name: 'Spice Box', components: [{ name: 'Cumin', unit: '', quantity: '3' }] })),
    )
  })
})
