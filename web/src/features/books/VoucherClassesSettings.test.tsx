import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ledgers as ledgersQuery } from '@/api/queries/books'
import { voucherClasses, type VoucherClass } from '@/api/queries/voucherClasses'
import type { LedgerAccount } from '@/api/types'
import { VoucherClassesSettings } from './VoucherClassesSettings'

const post = vi.fn()
const del = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), delete: (...a: unknown[]) => del(...a), get: vi.fn(), patch: vi.fn() } }))

const ledger = (id: string, name: string, group: string) => ({ id, name, group, status: 'ACTIVE', is_active: true }) as unknown as LedgerAccount
const CLASSES: VoucherClass[] = [{ id: 'k1', name: 'Retail 18%', voucher_type: 'Sales', type_name: '', head_ledger: 'l5', head_ledger_name: 'Retail Sales', gst_rate: '18.00' }]

function setup(mayEdit = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } })
  queryClient.setQueryData(voucherClasses('c1').queryKey, CLASSES)
  queryClient.setQueryData(ledgersQuery('c1').queryKey, [ledger('l5', 'Retail Sales', 'SALES'), ledger('l1', 'Purchases', 'PURCHASE')])
  render(
    <QueryClientProvider client={queryClient}>
      <VoucherClassesSettings clientId="c1" mayEdit={mayEdit} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  post.mockReset()
  del.mockReset()
})

describe('VoucherClassesSettings', () => {
  it('lists each class with its ledger and rate', () => {
    setup()
    const list = within(screen.getByRole('list', { name: 'Voucher classes' }))
    expect(list.getByText('Retail 18%')).toBeInTheDocument()
    expect(list.getByText(/Retail Sales/)).toBeInTheDocument()
    expect(list.getByText(/18\.00%/)).toBeInTheDocument()
  })

  it('adds a class', async () => {
    post.mockResolvedValue({ ...CLASSES[0], id: 'k2', name: 'Retail 5%' })
    const user = userEvent.setup()
    setup()
    await user.type(screen.getByLabelText('Class name'), 'Retail 5%')
    fireEvent.change(screen.getByLabelText('Class is for'), { target: { value: 'Sales' } })
    fireEvent.change(screen.getByLabelText('Class ledger'), { target: { value: 'l5' } })
    await user.type(screen.getByLabelText('Class GST rate'), '5')
    await user.click(screen.getByRole('button', { name: 'Add class' }))
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/clients/c1/voucher-classes/', { name: 'Retail 5%', voucher_type: 'Sales', head_ledger: 'l5', gst_rate: '5' }),
    )
  })

  it('removes a class', async () => {
    del.mockResolvedValue(undefined)
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Remove Retail 18%' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/api/v1/clients/c1/voucher-classes/k1/'))
  })

  it('cannot be changed by someone who may not edit', () => {
    setup(false)
    expect(screen.queryByRole('button', { name: 'Add class' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove Retail 18%' })).not.toBeInTheDocument()
  })
})
