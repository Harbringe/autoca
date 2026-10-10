import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { bills as billsQuery, invoiceReadings } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import type { Bill, Client, InvoiceReading } from '@/api/types'
import { PurchasesScreen } from './PurchasesScreen'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@/features/shell/useFy', () => ({ useFy: () => ({ fy: 2025 }) }))
const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (importOriginal) => ({ ...(await importOriginal<typeof import('@tanstack/react-router')>()), useNavigate: () => navigate }))

const bill = (over: Partial<Bill>): Bill =>
  ({ id: 'b1', kind: 'PURCHASE', party: 'p1', party_name: 'Ravi Traders', reference: 'INV-1', bill_date: '2025-10-01', financial_year: 2025, total_paise: 118000, open_paise: 118000, document: null, has_document: false, created_at: '2025-10-01T10:00:00Z', ...over }) as unknown as Bill

const reading = (over: Partial<InvoiceReading>): InvoiceReading =>
  ({ id: 'r1', kind: 'PURCHASE', status: 'OPEN', document: 'd1', filename: 'jubilant.jpeg', proved: true, unreadable_reason: '', attention: '', auto_booked: false, checks: [], created_at: '2025-10-02T10:00:00Z', bill: null, read: null, ...over }) as unknown as InvoiceReading

const WAITING = reading({
  id: 'r2',
  document: 'd2',
  read: { supplier_name: 'Jubilant FoodWorks Limited', supplier_address: 'Pune, India', invoice_no: '80154', invoice_date: '2025-09-27', total_paise: 108300, unsure: [] } as never,
  attention: 'The client’s GSTIN is not on this file.',
})

function renderIt(data: { bills?: Bill[]; readings?: InvoiceReading[] } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(billsQuery('c1').queryKey, data.bills ?? [bill({}), bill({ id: 'b3', kind: 'SALES', party_name: 'Mehta Stores', reference: 'SL-1', total_paise: 500000, open_paise: 0, bill_date: '2025-10-05' })])
  queryClient.setQueryData(invoiceReadings('c1').queryKey, data.readings ?? [WAITING])
  queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Acme', can_post: true } as unknown as Client)
  render(
    <QueryClientProvider client={queryClient}>
      <PurchasesScreen clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  navigate.mockReset()
  vi.mocked(raw.post).mockReset()
  vi.mocked(raw.delete).mockReset()
})

describe('Purchases & Sales as a list of receipts', () => {
  it('lists every receipt in one table: filed ones, bills keyed in, and a file waiting with its alert', async () => {
    renderIt()
    const table = await screen.findByRole('table', { name: /Purchases and sales, FY 2025-26/ })
    expect(within(table).getByText('Jubilant FoodWorks Limited')).toBeInTheDocument()
    expect(within(table).getByText('Pune, India')).toBeInTheDocument()
    expect(within(table).getByText('Needs you')).toBeInTheDocument()
    expect(within(table).getByText('Ravi Traders')).toBeInTheDocument()
    expect(within(table).getByText('Mehta Stores')).toBeInTheDocument()
    expect(within(table).getByRole('img', { name: /Alert: The client’s GSTIN is not on this file/ })).toBeInTheDocument()
  })

  it('narrows to purchases or to sales', async () => {
    renderIt()
    await userEvent.click(await screen.findByRole('tab', { name: /Sales/ }))
    const table = screen.getByRole('table')
    expect(within(table).getByText('Mehta Stores')).toBeInTheDocument()
    expect(within(table).queryByText('Ravi Traders')).not.toBeInTheDocument()
  })

  it('opens a row on its own page', async () => {
    renderIt()
    await userEvent.click(await screen.findByText('Jubilant FoodWorks Limited'))
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({ to: '/clients/$clientId/bills/$itemId', params: { clientId: 'c1', itemId: 'r2' }, search: { as: 'reading' } }))
  })

  it('lists the alerts, with the reason for each', async () => {
    renderIt()
    await userEvent.click(await screen.findByRole('button', { name: /3 rows need a look/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Alerts' })
    expect(within(dialog).getByText('The client’s GSTIN is not on this file.')).toBeInTheDocument()
    expect(within(dialog).getAllByText('No invoice file is attached to this bill.')).toHaveLength(2)
  })

  it('reads dropped files, shows them processing, and opens a single one that needs the person', async () => {
    let finish: (r: InvoiceReading) => void = () => {}
    vi.mocked(raw.post).mockImplementation(() => new Promise((resolve) => (finish = resolve as never)))
    renderIt()

    await userEvent.upload(await screen.findByLabelText('Choose receipts'), new File(['x'], 'lunch.jpg', { type: 'image/jpeg' }))
    expect(await screen.findByText('Processing lunch.jpg')).toBeInTheDocument()
    finish(reading({ id: 'r9', status: 'OPEN' }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith(expect.objectContaining({ params: { clientId: 'c1', itemId: 'r9' } })))
    expect(vi.mocked(raw.post).mock.calls[0]![0]).toContain('/invoices/upload/')
  })

  it('deletes the chosen rows after asking', async () => {
    vi.mocked(raw.delete).mockResolvedValue(undefined)
    renderIt()
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Select Jubilant FoodWorks Limited' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click((await screen.findAllByRole('button', { name: 'Delete' })).at(-1)!)
    await waitFor(() => expect(raw.delete).toHaveBeenCalledWith(expect.stringContaining('/invoices/r2/')))
  })

  it('invites the first receipt when there are none', async () => {
    renderIt({ bills: [], readings: [] })
    expect(await screen.findByText('No purchases or sales in FY 2025-26')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Upload receipts/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Create manually/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Waiting for you \(0\)/ })).toBeDisabled()
  })
})
