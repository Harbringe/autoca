import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { bills as billsQuery } from '@/api/queries/bills'
import { ledgers as ledgersQuery, parties as partiesQuery } from '@/api/queries/books'
import { clientDetail } from '@/api/queries/clients'
import { gstRegistrations } from '@/api/queries/gst'
import type { Client, GstRegistration } from '@/api/types'
import { VoucherForm, type VoucherPrefill } from './VoucherDialog'

vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: vi.fn(), get: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))

const CLIENT = 'c1'
const reg = (id: string, gstin: string, state: string) => ({ id, gstin, state_code: state, registration_type: 'regular' }) as GstRegistration
const BASE: VoucherPrefill = { kind: 'PURCHASE', reference: 'SI/1', billDate: '2025-04-19', taxablePaise: 100_000, cgstPaise: 2500, sgstPaise: 2500, igstPaise: 0, cessPaise: 0, roundOffPaise: 0 }

function setup(registrations: GstRegistration[], prefill: Partial<VoucherPrefill> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(billsQuery(CLIENT).queryKey, [])
  queryClient.setQueryData(partiesQuery(CLIENT).queryKey, [])
  queryClient.setQueryData(ledgersQuery(CLIENT).queryKey, [])
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Acme', can_post: true } as unknown as Client)
  queryClient.setQueryData(gstRegistrations(CLIENT).queryKey, registrations)
  render(
    <QueryClientProvider client={queryClient}>
      <VoucherForm clientId={CLIENT} onClose={() => {}} prefill={{ ...BASE, ...prefill }} />
    </QueryClientProvider>,
  )
}

describe("the client's GSTIN on an invoice", () => {
  it('is chosen from the client’s own GSTINs, and filled in when there is only one', async () => {
    setup([reg('r1', '27BCKPK1187P1ZX', '27')])
    const select = (await screen.findByLabelText('Client’s GSTIN on this invoice')) as HTMLSelectElement
    expect(select.value).toBe('27BCKPK1187P1ZX')
  })

  it('offers each of several GSTINs and waits to be told which, unless the invoice named one', async () => {
    setup([reg('r1', '27BCKPK1187P1ZX', '27'), reg('r2', '29AAACA1234B1Z5', '29')])
    const select = (await screen.findByLabelText('Client’s GSTIN on this invoice')) as HTMLSelectElement
    expect(select.value).toBe('')
    expect([...select.options].map((o) => o.value)).toEqual(['', '27BCKPK1187P1ZX', '29AAACA1234B1Z5'])
  })

  it('keeps the GSTIN the invoice printed when the client has no such one yet, and offers to add it', async () => {
    const user = userEvent.setup()
    setup([reg('r1', '27BCKPK1187P1ZX', '27')], { ownGstin: '29AAACA1234B1Z5' })
    const select = (await screen.findByLabelText('Client’s GSTIN on this invoice')) as HTMLSelectElement
    expect(select.value).toBe('29AAACA1234B1Z5')
    expect(screen.getByText(/not on record/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add a GSTIN for this client' }))
    // the dialog opens with what the invoice printed already typed
    expect(await screen.findByRole('dialog', { name: 'Add a GSTIN' })).toBeInTheDocument()
    expect(screen.getByLabelText('GSTIN')).toHaveValue('29AAACA1234B1Z5')
  })
})
