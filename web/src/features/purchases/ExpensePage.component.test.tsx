import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { bill as billQuery, bills as billsQuery, invoiceReadings } from '@/api/queries/bills'
import { ledgers as ledgersQuery, parties as partiesQuery } from '@/api/queries/books'
import { clientDetail } from '@/api/queries/clients'
import type { Bill, BillDetail, Client, InvoiceReading, LedgerAccount, Party } from '@/api/types'
import { ExpensePage } from './ExpensePage'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  useNavigate: () => navigate,
  Link: ({ children, ...rest }: { children: React.ReactNode }) => <a {...(rest as object)}>{children}</a>,
}))

const ledger = (id: string, name: string, group: string): LedgerAccount => ({ id, name, group, status: 'ACTIVE', is_active: true, is_bank_or_cash: false }) as unknown as LedgerAccount
const LEDGERS = [ledger('l1', 'Purchases', 'PURCHASE'), ledger('l2', 'Sales', 'SALES'), ledger('l3', 'Food & Beverages Expenses', 'INDIRECT_EXPENSE')]
const PARTIES = [{ id: 'p1', canonical_name: 'Jubilant FoodWorks Limited', role: 'VENDOR', is_active: true, gstin: '', ledger: null }] as unknown as Party[]

const READ = {
  supplier_name: 'Jubilant FoodWorks Limited',
  gstins: [],
  counterparty_gstin: '',
  invoice_no: '80154/26/O4160',
  invoice_date: '2026-09-27',
  taxable_paise: 100000,
  cgst_paise: 0,
  sgst_paise: 0,
  igst_paise: 0,
  cess_paise: 0,
  round_off_paise: 0,
  total_paise: 108300,
  total_display: '₹1,083.00',
  unsure: [],
  due_date: null,
  supplier_address: 'Silver Stone, Handewadi, Pune',
  supplier_pan: '',
  supplier_gstin: '27ABTPN5133F1ZF',
  buyer_gstin: '27AAACB2230M1ZT',
  buyer_name: 'Acme Traders',
  buyer_address: 'Mondha, Loha',
  place_of_supply: 'Maharashtra',
  payment_mode: 'card',
  payment_terms: '',
  currency: 'INR',
  expense_hint: 'Food and beverages',
  items: [
    { description: 'Biryani', hsn_sac: '9963', quantity: '2', unit: 'plate', rate_paise: 30000, amount_paise: 60000, gst_rate: 5 },
    { description: 'Thali', hsn_sac: '9963', quantity: '1', unit: '', rate_paise: 40000, amount_paise: 40000, gst_rate: 5 },
  ],
}

const READING = {
  id: 'r1',
  kind: 'PURCHASE',
  status: 'OPEN',
  document: 'd1',
  filename: 'lunch.jpeg',
  proved: true,
  unreadable_reason: '',
  attention: '',
  auto_booked: false,
  checks: [],
  created_at: '2026-10-05T10:00:00Z',
  suggested_party: { id: 'p1', name: 'Jubilant FoodWorks Limited' },
  matching_bill: null,
  bill: null,
  payments: [],
  read: READ,
} as unknown as InvoiceReading

function renderIt(props: Partial<React.ComponentProps<typeof ExpensePage>> = {}, readings: InvoiceReading[] = [READING], bills: Bill[] = [], detail?: BillDetail) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(invoiceReadings('c1').queryKey, readings)
  queryClient.setQueryData(billsQuery('c1').queryKey, bills)
  queryClient.setQueryData(partiesQuery('c1').queryKey, PARTIES)
  queryClient.setQueryData(ledgersQuery('c1').queryKey, LEDGERS)
  queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Acme', can_post: true } as unknown as Client)
  if (detail) queryClient.setQueryData(billQuery('c1', detail.id).queryKey, detail)
  render(
    <QueryClientProvider client={queryClient}>
      <ExpensePage clientId="c1" itemId="r1" as="reading" {...props} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  navigate.mockReset()
  vi.mocked(raw.post).mockReset()
  vi.mocked(raw.get).mockImplementation(async () => ({ pages: 1, filename: 'lunch.jpeg' }))
})

describe('one purchase or sale on its own page', () => {
  it('fills the form from the receipt and shows the receipt beside it', async () => {
    renderIt()

    expect(await screen.findByRole('heading', { name: /Purchase invoice · Jubilant FoodWorks Limited/ })).toBeInTheDocument()
    expect(screen.getByText('AI-assisted')).toBeInTheDocument()
    expect(screen.getByDisplayValue('80154/26/O4160')).toBeInTheDocument()
    expect(screen.getByDisplayValue('27-09-2026')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Supplier' })).toHaveValue('p1')
    const facts = screen.getByRole('region', { name: 'Read from the receipt' })
    expect(within(facts).getByText('Card')).toBeInTheDocument()
    // The two sides of the invoice read From, To: the supplier's printed details and the client's own GSTIN, filled in.
    const sides = screen.getByRole('region', { name: 'From and to' })
    expect(within(sides).getByText('Silver Stone, Handewadi, Pune')).toBeInTheDocument()
    expect(within(sides).getByText('From · seller')).toBeInTheDocument()
    expect(within(sides).getByText('To · buyer')).toBeInTheDocument()
    expect(within(sides).getByLabelText('GSTIN on this invoice')).toHaveValue('27AAACB2230M1ZT')
    // The narration is worked out from the lines, the party and the invoice number.
    expect(screen.getByLabelText('Narration')).toHaveValue('Being purchase of Biryani, Thali from Jubilant FoodWorks Limited vide invoice 80154/26/O4160')
    expect(await screen.findByAltText('Page 1 of 1 of the uploaded file')).toBeInTheDocument()
    expect(screen.getByText('lunch.jpeg')).toBeInTheDocument()
  })

  it('points the taxable value at the ledger the receipt says it was for', async () => {
    renderIt()
    expect(await screen.findByPlaceholderText('Food & Beverages Expenses')).toBeInTheDocument()
  })

  it('lists the printed lines and offers one ledger line per item when they add up', async () => {
    renderIt()
    await userEvent.click(await screen.findByRole('tab', { name: 'Itemizations (2)' }))
    const lines = screen.getByRole('list', { name: 'Lines as printed on the invoice' })
    expect(within(lines).getByDisplayValue('Biryani')).toBeInTheDocument()
    expect(within(lines).getAllByDisplayValue('9963')).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: 'Use one line per item' }))

    expect(screen.getAllByRole('textbox', { name: 'Amount (₹)' })).toHaveLength(2)
    expect(screen.getByText('Biryani')).toBeInTheDocument()
  })

  it('lets a line be corrected, and offers the quantity this party usually sends', async () => {
    const withUsual = {
      ...READING,
      read: { ...READ, items: READ.items.map((i, n) => (n === 0 ? { ...i, quantity: '6', usual_quantity: '60', remembered: true, read_description: 'FPPUS 120 Bags' } : i)) },
    } as unknown as InvoiceReading
    renderIt({}, [withUsual])
    await userEvent.click(await screen.findByRole('tab', { name: /Itemizations/ }))
    const description = screen.getByLabelText('Description of line 1')
    await userEvent.clear(description)
    await userEvent.type(description, 'Cement PPC')
    expect(description).toHaveValue('Cement PPC')
    expect(screen.getByLabelText('Quantity of line 1')).toHaveValue('6')
    await userEvent.click(screen.getByRole('button', { name: 'Usually 60' }))
    expect(screen.getByLabelText('Quantity of line 1')).toHaveValue('60')
  })

  it('offers to read the lines again when none were read, and asks the server to', async () => {
    const empty = { ...READING, read: { ...READ, items: [] } } as unknown as InvoiceReading
    renderIt({}, [empty])
    await userEvent.click(await screen.findByRole('tab', { name: /Itemizations/ }))
    expect(screen.getByText(/No lines were read from this invoice/)).toBeInTheDocument()
    // The server's answer has the lines now, and the list of readings is read again after it.
    vi.mocked(raw.post).mockResolvedValue(READING)
    vi.mocked(raw.get).mockImplementation(async (path: string) => (path.includes('/invoices/') ? { results: [READING], next: null } : { pages: 1, filename: 'lunch.jpeg' }))
    await userEvent.click(screen.getByRole('button', { name: 'Read the lines again' }))
    expect(raw.post).toHaveBeenCalledWith(expect.stringContaining('/reread/'), {})
    // The form shows the new lines, not the empty ones it started with.
    expect(await screen.findByLabelText('Description of line 1')).toHaveValue('Biryani')
    expect(screen.queryByText(/No lines were read from this invoice/)).not.toBeInTheDocument()
  })

  it('selects the party already on file when the invoice names it in other words, instead of offering to add it again', async () => {
    const unmatched = { ...READING, suggested_party: null, read: { ...READ, supplier_name: 'JUBILANT FOODWORKS LTD.' } } as unknown as InvoiceReading
    renderIt({}, [unmatched])
    expect(await screen.findByText(/Matched to Jubilant FoodWorks Limited, already on file/)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Supplier' })).toHaveValue('p1')
    expect(screen.queryByLabelText('GSTIN (blank if unregistered)')).not.toBeInTheDocument()
  })

  it('warns when the invoice is made out to someone other than the client', async () => {
    renderIt()
    // The client is Acme; the invoice says Acme Traders, which is the same business, so no warning.
    await screen.findByRole('region', { name: 'From and to' })
    expect(screen.queryByText(/Check it is the right client/)).not.toBeInTheDocument()
    const other = { ...READING, read: { ...READ, buyer_name: 'S.B.H Dryfruits' } } as unknown as InvoiceReading
    cleanup()
    renderIt({}, [other])
    expect(await screen.findByText(/made out to “S.B.H Dryfruits”, not to Acme/)).toBeInTheDocument()
  })

  it('says only Save while the type is not known, and fills the party from the invoice once it is chosen', async () => {
    const unsure = {
      ...READING,
      kind: '',
      suggested_party: null,
      read: { ...READ, suggested_kind: '', supplier_name: 'Brand New Supplier', supplier_gstin: '27AAAAA0000A1Z5' },
    } as unknown as InvoiceReading
    renderIt({}, [unsure])
    expect(await screen.findByRole('button', { name: 'Save' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Voucher type' })).toHaveValue('')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Voucher type' }), 'PURCHASE')
    // Not on file, so the new-supplier panel opens with what the invoice printed.
    expect(await screen.findByDisplayValue('Brand New Supplier')).toBeInTheDocument()
    expect(screen.getByDisplayValue('27AAAAA0000A1Z5')).toBeInTheDocument()
  })

  it('shows the document in words and keeps boilerplate behind the first few facts', async () => {
    const wordy = {
      ...READING,
      read: { ...READ, details: { document_type: 'tax_invoice', notes: 'Goods once sold will not be taken back.', po_number: 'PO-9' } },
    } as unknown as InvoiceReading
    renderIt({}, [wordy])
    const facts = await screen.findByRole('region', { name: 'Read from the receipt' })
    expect(within(facts).getByText('Tax invoice')).toBeInTheDocument()
    expect(within(facts).queryByText('tax_invoice')).not.toBeInTheDocument()
  })

  it('reads To, From the other way round on a sale', async () => {
    const sale = { ...READING, kind: 'SALES', suggested_party: null, read: { ...READ, supplier_name: 'Acme Traders', buyer_name: 'New Customer Stores' } } as unknown as InvoiceReading
    renderIt({}, [sale])
    const sides = await screen.findByRole('region', { name: 'From and to' })
    expect(within(sides).getByText('From · seller')).toBeInTheDocument()
    expect(within(sides).getByRole('combobox', { name: 'Customer' })).toBeInTheDocument()
  })

  it('hides and shows the receipt viewer', async () => {
    renderIt()
    await userEvent.click(await screen.findByRole('button', { name: /Hide receipt viewer/ }))
    expect(screen.queryByRole('complementary', { name: 'Receipt' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show receipt viewer' }))
    expect(screen.getByRole('complementary', { name: 'Receipt' })).toBeInTheDocument()
  })

  it('says what to look at before saving', async () => {
    renderIt({}, [{ ...READING, proved: false, checks: [{ name: 'arithmetic', ok: false, detail: 'Taxable value plus tax does not equal the total.' }], read: { ...READ, unsure: ['invoice_date'] } } as unknown as InvoiceReading])
    await userEvent.click(await screen.findByRole('button', { name: /View alerts \(2\)/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Alerts' })
    expect(within(dialog).getByText('Taxable value plus tax does not equal the total.')).toBeInTheDocument()
    expect(within(dialog).getByText(/not sure of: invoice_date/)).toBeInTheDocument()
  })

  it('on a new one asks for the receipt, reads it, and moves to its page', async () => {
    vi.mocked(raw.post).mockResolvedValue({ ...READING, id: 'r7' })
    renderIt({ as: 'new', itemId: 'new', kind: 'SALES' }, [])

    expect(await screen.findByRole('heading', { name: 'New sales invoice' })).toBeInTheDocument()
    expect(screen.getByText('Upload or drag and drop the receipt here')).toBeInTheDocument()
    await userEvent.upload(screen.getByLabelText('Choose a receipt'), new File(['x'], 'bill.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith(expect.objectContaining({ params: { clientId: 'c1', itemId: 'r7' }, search: { as: 'reading' }, replace: true })))
    const form = vi.mocked(raw.post).mock.calls[0]![1] as FormData
    expect(form.get('book')).toBe('false')
  })

  it('shows a booked bill with what is on the books and a Save changes button', async () => {
    const bill = {
      id: 'b1', kind: 'PURCHASE', party: 'p1', party_name: 'Jubilant FoodWorks Limited', reference: '80154', bill_date: '2026-09-27', due_date: null,
      taxable_paise: 100000, cgst_paise: 0, sgst_paise: 0, igst_paise: 0, cess_paise: 0, round_off_paise: 0, tds_paise: 0, rcm: false,
      total_paise: 100000, total_display: '₹1,000.00', open_paise: 100000, open_display: '₹1,000.00', document: 'd1', has_document: true, is_locked: false,
      voucher_type: 'Purchase', entry_no: 7, lines: [], allocations: [],
    } as unknown as BillDetail
    renderIt({ as: 'bill', itemId: 'b1' }, [{ ...READING, status: 'BOOKED', bill: 'b1' } as unknown as InvoiceReading], [bill as unknown as Bill], bill)

    expect(await screen.findByRole('button', { name: 'Save changes' })).toBeInTheDocument()
    const books = screen.getByRole('region', { name: 'On the books' })
    expect(within(books).getByText('Nothing yet. A payment from the bank statement will settle it.')).toBeInTheDocument()
    expect(screen.getByText('Purchase No. 7')).toBeInTheDocument()
  })
})
