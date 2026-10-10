import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { bills as billsQuery } from '@/api/queries/bills'
import { ledgers as ledgersQuery, parties as partiesQuery } from '@/api/queries/books'
import { clientDetail } from '@/api/queries/clients'
import type { Bill, Client, LedgerAccount, Party } from '@/api/types'
import { VoucherDialog } from './VoucherDialog'

vi.mock('@/session/session', () => ({
  useSession: () => ({ me: { permissions: ['journal.approve', 'journal.view'] }, can: () => true }),
}))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))

const CLIENT = 'c1'

const party = (id: string, name: string, role: string): Party =>
  ({ id, canonical_name: name, role, is_active: true, gstin: '', ledger: null }) as unknown as Party
const ledger = (id: string, name: string, group: string): LedgerAccount =>
  ({ id, name, group, status: 'ACTIVE', is_active: true, is_bank_or_cash: group === 'BANK' }) as unknown as LedgerAccount

const PARTIES = [party('p1', 'Ravi Traders', 'VENDOR'), party('p2', 'Mehta Stores', 'CUSTOMER'), party('p3', 'Both Ways Ltd', 'BOTH')]
const LEDGERS = [ledger('l1', 'Purchases', 'PURCHASE'), ledger('l2', 'Sales', 'SALES'), ledger('l3', 'Axis Bank A/c 9999', 'BANK')]

function bill(over: Partial<Bill> & Pick<Bill, 'id' | 'kind' | 'party_name' | 'reference'>): Bill {
  return {
    direction: 'CR',
    kind_display: over.kind,
    party: 'p1',
    bill_date: '2025-10-01',
    due_date: null,
    booked_on: '2025-10-01',
    financial_year: 2025,
    total_paise: 11_800_000,
    total_display: '₹1,18,000.00',
    open_paise: 11_800_000,
    open_display: '₹1,18,000.00',
    entry: 'e1',
    entry_no: 1,
    voucher_type: 'Purchase',
    has_document: false,
    is_locked: false,
    ...over,
  } as unknown as Bill
}

const BILLS = [
  bill({ id: 'b1', kind: 'PURCHASE', party_name: 'Ravi Traders', reference: 'INV-1' }),
  bill({ id: 'b2', kind: 'PURCHASE', party_name: 'Shah Stationers', reference: 'S-9', open_paise: 0, open_display: '₹0.00', has_document: true, bill_date: '2025-09-01' }),
  bill({ id: 'b3', kind: 'SALES', party_name: 'Mehta Stores', reference: 'SL-1', total_paise: 5_000_000, total_display: '₹50,000.00', open_paise: 5_000_000, open_display: '₹50,000.00', voucher_type: 'Sales', direction: 'DR', bill_date: '2025-10-05' }),
  bill({ id: 'b4', kind: 'PURCHASE', party_name: 'Last Year Ltd', reference: 'OLD', financial_year: 2024, bill_date: '2025-02-01' }),
]

function renderWith(ui: React.ReactElement, data: { bills?: Bill[] } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(billsQuery(CLIENT).queryKey, data.bills ?? BILLS)
  queryClient.setQueryData(partiesQuery(CLIENT).queryKey, PARTIES)
  queryClient.setQueryData(ledgersQuery(CLIENT).queryKey, LEDGERS)
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Acme', can_post: true } as unknown as Client)
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('Booking a voucher', () => {
  const open = () => renderWith(<VoucherDialog clientId={CLIENT} open onOpenChange={() => {}} />)

  it('works out the supplier’s account as the figures are typed', async () => {
    open()
    await userEvent.type(await screen.findByLabelText('Amount (₹)'), '1,00,000')
    await userEvent.type(screen.getByLabelText('CGST'), '9000')
    await userEvent.type(screen.getByLabelText('SGST'), '9000')
    const preview = screen.getByRole('region', { name: 'What this comes to' })
    expect(preview).toHaveTextContent('Supplier’s account (Cr)')
    expect(preview).toHaveTextContent('₹1,18,000.00')
  })

  it('fills the round off that brings the total to a whole rupee, up or down', async () => {
    open()
    await userEvent.type(await screen.findByLabelText('Amount (₹)'), '16780.20')
    await userEvent.type(screen.getByLabelText('CGST'), '1510.21')
    await userEvent.type(screen.getByLabelText('SGST'), '1510.21')
    await userEvent.click(screen.getByRole('button', { name: 'Round off' }))
    expect(screen.getByLabelText(/Round off \(₹/)).toHaveValue('0.38') // 19,800.62 up to 19,801
    expect(screen.getByRole('region', { name: 'What this comes to' })).toHaveTextContent('₹19,801.00')

    await userEvent.clear(screen.getByLabelText('SGST'))
    await userEvent.type(screen.getByLabelText('SGST'), '1509.90')
    await userEvent.click(screen.getByRole('button', { name: 'Round off' }))
    expect(screen.getByLabelText(/Round off \(₹/)).toHaveValue('-0.31') // 19,800.31 rounds down to 19,800
  })

  it('under reverse charge the supplier is owed only the taxable value', async () => {
    open()
    await userEvent.type(await screen.findByLabelText('Amount (₹)'), '1,00,000')
    await userEvent.type(screen.getByLabelText('CGST'), '9000')
    await userEvent.type(screen.getByLabelText('SGST'), '9000')
    await userEvent.click(screen.getByLabelText(/Reverse charge/))
    expect(screen.getByRole('region', { name: 'What this comes to' })).toHaveTextContent('₹1,00,000.00')
  })

  it('TDS is deducted from what the supplier is owed', async () => {
    open()
    await userEvent.type(await screen.findByLabelText('Amount (₹)'), '50,000')
    await userEvent.type(screen.getByLabelText('IGST'), '9000')
    await userEvent.type(screen.getByLabelText(/TDS deducted/), '5000')
    expect(screen.getByRole('region', { name: 'What this comes to' })).toHaveTextContent('₹54,000.00')
  })

  it('says why, in the server’s words, when the figures cannot make a voucher', async () => {
    open()
    await userEvent.type(await screen.findByLabelText('Amount (₹)'), '1,000')
    await userEvent.type(screen.getByLabelText('CGST'), '90')
    await userEvent.type(screen.getByLabelText('IGST'), '180')
    expect(screen.getByRole('status')).toHaveTextContent('CGST and SGST, or IGST, not both')
  })

  it('offers only suppliers on a purchase and only customers on a sale', async () => {
    open()
    const party = await screen.findByLabelText('Supplier')
    expect(within(party).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Choose…', 'Both Ways Ltd', 'Ravi Traders', '+ Add a new supplier…',
    ])
    await userEvent.selectOptions(screen.getByLabelText('Voucher type'), 'SALES')
    const customer = screen.getByLabelText('Customer')
    expect(within(customer).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Choose…', 'Both Ways Ltd', 'Mehta Stores', '+ Add a new customer…',
    ])
    // TDS and reverse charge belong to a purchase, not a sale.
    expect(screen.queryByLabelText(/TDS deducted/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Reverse charge/)).not.toBeInTheDocument()
  })

  it('never offers a bank, cash or party account as what an invoice is for', async () => {
    open()
    await screen.findByLabelText('Supplier')
    // The ledger picker lists what can hold an invoice's value; the bank account is not among them.
    await userEvent.click(screen.getAllByRole('combobox').find((el) => el.getAttribute('aria-label')?.startsWith('Ledger')) ?? screen.getAllByRole('combobox')[1]!)
    // (It is offered, on purpose, under "Paid from": that is where the money came out of.)
    expect(screen.queryAllByText('Axis Bank A/c 9999').filter((el) => el.tagName !== 'OPTION')).toHaveLength(0)
  })

  it('asks for what is missing instead of sending an empty voucher', async () => {
    open()
    await userEvent.click(await screen.findByRole('button', { name: 'Book voucher' }))
    expect(await screen.findByText('Choose the supplier.')).toBeInTheDocument()
    expect(screen.getByText('Enter the invoice number as printed.')).toBeInTheDocument()
    expect(screen.getByText('Choose where this goes.')).toBeInTheDocument()
  })
})
