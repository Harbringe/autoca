import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ledgers as ledgersQuery, parties as partiesQuery } from '@/api/queries/books'
import { bills as billsQuery } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import type { Client, LedgerAccount, Party } from '@/api/types'
import { VoucherForm, type VoucherPrefill } from './VoucherDialog'

const post = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))

const CLIENT = 'c1'
const ledger = (id: string, name: string, group: string) => ({ id, name, group, status: 'ACTIVE', is_active: true }) as unknown as LedgerAccount
const LEDGERS = [ledger('l1', 'Purchases', 'PURCHASE'), ledger('l9', 'Purchases - Sample Oil 1 LTR', 'PURCHASE'), ledger('l10', 'Purchases - Sample Oil 15 LTR', 'PURCHASE')]
const line = (description: string, amount_paise: number) =>
  ({ description, hsn_sac: '15079010', quantity: '10', unit: 'nos', rate_paise: amount_paise / 10, amount_paise, gst_rate: 5, gst_rate_derived: false }) as never

const PREFILL: VoucherPrefill = {
  kind: 'PURCHASE',
  reference: 'SI/1',
  billDate: '2025-04-19',
  taxablePaise: 100_000,
  cgstPaise: 2500,
  sgstPaise: 2500,
  igstPaise: 0,
  cessPaise: 0,
  roundOffPaise: 0,
  headLedger: 'l1',
  items: [line('Sample Oil 1 LTR', 40_000), line('Sample Oil 15 LTR', 60_000)],
}

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(billsQuery(CLIENT).queryKey, [])
  queryClient.setQueryData(partiesQuery(CLIENT).queryKey, [{ id: 'p1', canonical_name: 'Ravi Traders', role: 'VENDOR', is_active: true, gstin: '', ledger: null } as unknown as Party])
  queryClient.setQueryData(ledgersQuery(CLIENT).queryKey, LEDGERS)
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Acme', can_post: true } as unknown as Client)
  render(
    <QueryClientProvider client={queryClient}>
      <VoucherForm clientId={CLIENT} layout="page" formId="f" tab="items" onTabChange={() => {}} onClose={() => {}} prefill={PREFILL} />
    </QueryClientProvider>,
  )
}

beforeEach(() => post.mockReset())

describe('giving each invoice line a ledger of its own', () => {
  it('creates each line’s ledger and puts it in, when the button is pressed', async () => {
    post.mockResolvedValue({
      ledgers: [
        { description: 'Sample Oil 1 LTR', ledger: 'l9', ledger_name: 'Purchases - Sample Oil 1 LTR', created: true },
        { description: 'Sample Oil 15 LTR', ledger: 'l10', ledger_name: 'Purchases - Sample Oil 15 LTR', created: false },
      ],
    })
    const user = userEvent.setup()
    setup()
    await user.click(await screen.findByRole('button', { name: 'Use one line per item' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0]![0]).toBe('/api/v1/clients/c1/bills/item-ledgers/')
    expect(post.mock.calls[0]![1]).toMatchObject({ kind: 'PURCHASE', items: [{ description: 'Sample Oil 1 LTR' }, { description: 'Sample Oil 15 LTR' }] })
    // the Details tab then shows a row per line, each already in its own ledger
    await waitFor(() => expect(screen.getAllByPlaceholderText(/Purchases - Sample Oil/).length).toBe(2))
  })
})
