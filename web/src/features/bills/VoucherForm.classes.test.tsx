import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ledgers as ledgersQuery, parties as partiesQuery } from '@/api/queries/books'
import { bills as billsQuery } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import { voucherClasses, type VoucherClass } from '@/api/queries/voucherClasses'
import type { Client, LedgerAccount, Party } from '@/api/types'
import { VoucherForm } from './VoucherDialog'

vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: vi.fn(), get: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))

const CLIENT = 'c1'
const ledger = (id: string, name: string, group: string) => ({ id, name, group, status: 'ACTIVE', is_active: true }) as unknown as LedgerAccount
const CLASSES: VoucherClass[] = [
  { id: 'k1', name: 'Retail 18%', voucher_type: 'Sales', type_name: '', head_ledger: 'l5', head_ledger_name: 'Retail Sales', gst_rate: '18.00' },
  { id: 'k2', name: 'Bought 5%', voucher_type: 'Purchase', type_name: '', head_ledger: 'l1', head_ledger_name: 'Purchases', gst_rate: '5.00' },
]

function setup(kind: 'SALES' | 'PURCHASE' = 'SALES') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(billsQuery(CLIENT).queryKey, [])
  queryClient.setQueryData(partiesQuery(CLIENT).queryKey, [{ id: 'p1', canonical_name: 'Ravi Traders', role: 'CUSTOMER', is_active: true, gstin: '', ledger: null } as unknown as Party])
  queryClient.setQueryData(ledgersQuery(CLIENT).queryKey, [ledger('l5', 'Retail Sales', 'SALES'), ledger('l1', 'Purchases', 'PURCHASE')])
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Acme', can_post: true } as unknown as Client)
  queryClient.setQueryData(voucherClasses(CLIENT).queryKey, CLASSES)
  render(
    <QueryClientProvider client={queryClient}>
      <VoucherForm clientId={CLIENT} layout="page" formId="f" tab="details" onTabChange={() => {}} onClose={() => {}} initialKind={kind} />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('voucher classes on the voucher form', () => {
  it('offers only the classes of the voucher kind', async () => {
    setup('SALES')
    const select = await screen.findByLabelText('Voucher class')
    expect(select).toHaveTextContent('Retail 18%')
    expect(select).not.toHaveTextContent('Bought 5%')
  })

  it('fills the head ledger and, once an amount is typed, half the rate as CGST and half as SGST', async () => {
    const user = userEvent.setup()
    setup('SALES')
    await user.selectOptions(await screen.findByLabelText('Voucher class'), 'k1')
    await user.type(screen.getAllByLabelText('Amount (₹)')[0]!, '1000')
    await waitFor(() => expect(screen.getByLabelText('CGST')).toHaveValue('90.00'))
    expect(screen.getByLabelText('SGST')).toHaveValue('90.00')
    expect(screen.getByLabelText('IGST')).toHaveValue('')
  })

  it('leaves tax the person typed alone', async () => {
    const user = userEvent.setup()
    setup('SALES')
    await user.selectOptions(await screen.findByLabelText('Voucher class'), 'k1')
    await user.type(screen.getByLabelText('CGST'), '5')
    await user.type(screen.getAllByLabelText('Amount (₹)')[0]!, '1000')
    expect(screen.getByLabelText('CGST')).toHaveValue('5')
    expect(screen.getByLabelText('SGST')).toHaveValue('')
  })

  it('offers the purchase classes for a purchase', async () => {
    setup('PURCHASE')
    await screen.findByText(/What it is for/)
    expect(screen.getByLabelText('Voucher class')).toHaveTextContent('Bought 5%')
  })
})
