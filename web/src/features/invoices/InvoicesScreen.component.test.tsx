import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { invoiceReadings } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import type { Client, InvoiceReading } from '@/api/types'
import { InvoicesScreen } from './InvoicesScreen'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/session/session', () => ({
  useSession: () => ({ me: { permissions: [] }, can: () => true }),
}))

const CLIENT = 'c1'

const READ = {
  supplier_name: 'RAVI TRADERS',
  gstins: [],
  counterparty_gstin: '27AABCR1234F1Z5',
  invoice_no: 'RT/042',
  invoice_date: '2025-08-12',
  taxable_paise: 1000000,
  cgst_paise: 90000,
  sgst_paise: 90000,
  igst_paise: 0,
  cess_paise: 0,
  round_off_paise: 0,
  total_paise: 1180000,
  total_display: '₹11,800.00',
}

const base = {
  kind: 'PURCHASE',
  status: 'OPEN',
  status_display: 'Waiting for a person',
  created_at: '2025-08-13T10:00:00Z',
  suggested_party: null,
  matching_bill: null,
  bill: null,
  unreadable_reason: '',
  auto_booked: false,
  attention: '',
  payments: [],
}

const READINGS = [
  {
    ...base,
    id: 'r1',
    document: 'd1',
    filename: 'ravi-042.pdf',
    proved: true,
    checks: [{ name: 'arithmetic', ok: true, detail: '' }],
    read: READ,
  },
  {
    ...base,
    id: 'r2',
    document: 'd2',
    filename: 'wrong-total.pdf',
    proved: false,
    checks: [{ name: 'arithmetic', ok: false, detail: 'Taxable value plus tax and round-off does not equal the total.' }],
    read: { ...READ, invoice_no: 'RT/043' },
  },
  {
    ...base,
    id: 'r3',
    document: 'd3',
    filename: 'photo.pdf',
    proved: false,
    checks: [],
    read: null,
    unreadable_reason: 'This looks like a scan or a photo, which cannot be read yet.',
  },
  {
    ...base,
    id: 'r4',
    document: 'd4',
    filename: 'auto.pdf',
    status: 'BOOKED',
    status_display: 'Booked as a bill',
    bill: 'b1',
    auto_booked: true,
    proved: true,
    checks: [{ name: 'arithmetic', ok: true, detail: '' }],
    read: { ...READ, invoice_no: 'RT/900' },
  },
  {
    ...base,
    id: 'r5',
    document: 'd5',
    filename: 'unknown.pdf',
    kind: '',
    attention: 'This client’s own GSTIN is not on record, so the file could not be told as a purchase or a sale.',
    proved: true,
    checks: [{ name: 'arithmetic', ok: true, detail: '' }],
    read: { ...READ, invoice_no: 'RT/901' },
  },
] as unknown as InvoiceReading[]

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Acme', can_post: true } as unknown as Client)
  queryClient.setQueryData(invoiceReadings(CLIENT).queryKey, READINGS)
  render(
    <QueryClientProvider client={queryClient}>
      <InvoicesScreen clientId={CLIENT} />
    </QueryClientProvider>,
  )
}

describe('Invoices', () => {
  it('says how many are waiting and lists each file with its status', async () => {
    renderScreen()
    expect(await screen.findByText(/4 invoices waiting for you/)).toBeInTheDocument()
    expect(screen.getByText('ravi-042.pdf')).toBeInTheDocument()
    expect(screen.getByText('wrong-total.pdf')).toBeInTheDocument()
  })

  it('shows what was proved, and says plainly what did not add up', async () => {
    renderScreen()
    const proved = (await screen.findByText('ravi-042.pdf')).closest('li')!
    expect(within(proved).getByText('Taxable value and tax add up to the total')).toBeInTheDocument()
    const faulty = screen.getByText('wrong-total.pdf').closest('li')!
    expect(within(faulty).getByText(/does not equal the total/)).toBeInTheDocument()
  })

  it('does not offer to book a scan, and says why it was not read', async () => {
    renderScreen()
    const scan = (await screen.findByText('photo.pdf')).closest('li')!
    expect(within(scan).getByText(/scan or a photo/)).toBeInTheDocument()
    expect(within(scan).queryByRole('button', { name: 'Book it' })).not.toBeInTheDocument()
    expect(within(scan).getByRole('button', { name: 'Set aside' })).toBeInTheDocument()
  })

  it('opens the voucher form filled in from the reading when booking', async () => {
    renderScreen()
    const proved = (await screen.findByText('ravi-042.pdf')).closest('li')!
    await userEvent.click(within(proved).getByRole('button', { name: 'Book it' }))
    expect(await screen.findByDisplayValue('RT/042')).toBeInTheDocument()
    expect(screen.getByDisplayValue('12-08-2025')).toBeInTheDocument()
  })

  it('shows an invoice the system booked, and lets a person change it', async () => {
    renderScreen()
    const auto = (await screen.findByText('auto.pdf')).closest('li')!
    expect(within(auto).getByText('Booked automatically')).toBeInTheDocument()
    expect(within(auto).getByRole('button', { name: 'Change' })).toBeInTheDocument()
    expect(within(auto).queryByRole('button', { name: 'Book it' })).not.toBeInTheDocument()
  })

  it('says why it could not tell, and lets a person say purchase or sale instead of booking blind', async () => {
    renderScreen()
    const unknown = (await screen.findByText('unknown.pdf')).closest('li')!
    expect(within(unknown).getByText(/own GSTIN is not on record/)).toBeInTheDocument()
    expect(within(unknown).getByRole('button', { name: 'It’s a purchase' })).toBeInTheDocument()
    expect(within(unknown).getByRole('button', { name: 'It’s a sale' })).toBeInTheDocument()
    expect(within(unknown).queryByRole('button', { name: 'Book it' })).not.toBeInTheDocument()
  })
})
