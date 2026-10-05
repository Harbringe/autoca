import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { outstanding, partyStatement } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import type { Client, Outstanding, PartyStatement } from '@/api/types'
import { financialYearOf, fyRange } from '@/lib/format'
import { OutstandingReport } from './OutstandingReport'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))

const CLIENT = 'c1'
const TODAY = new Date().toISOString().slice(0, 10)
const FY_START = fyRange(financialYearOf(TODAY)).from

const REPORT = {
  side: 'payables',
  as_of: TODAY,
  buckets: ['0-30', '31-60', '61-90', 'Over 90'],
  parties: [
    {
      party: 'p1',
      name: 'Ravi Traders',
      gstin_last4: 'K1Z7',
      bills: [
        { bill: 'b1', reference: 'OLD', kind: 'PURCHASE', kind_display: 'Purchase invoice', bill_date: '2025-04-01', due_date: null, age_days: 122, bucket: 'Over 90', open_paise: 100000, open_display: '₹1,000.00' },
        { bill: 'b2', reference: 'NEW', kind: 'PURCHASE', kind_display: 'Purchase invoice', bill_date: '2025-07-20', due_date: null, age_days: 12, bucket: '0-30', open_paise: 400000, open_display: '₹4,000.00' },
      ],
      bucket_paise: { '0-30': 400000, '31-60': 0, '61-90': 0, 'Over 90': 100000 },
      on_account_paise: -30000,
      on_account_display: '-₹300.00',
      total_paise: 470000,
      total_display: '₹4,700.00',
    },
  ],
  bucket_paise: { '0-30': 400000, '31-60': 0, '61-90': 0, 'Over 90': 100000 },
  on_account_paise: -30000,
  on_account_display: '-₹300.00',
  total_paise: 470000,
  total_display: '₹4,700.00',
} as unknown as Outstanding

const STATEMENT = {
  party: 'p1',
  name: 'Ravi Traders',
  date_from: FY_START,
  date_to: TODAY,
  opening_paise: 0,
  opening_display: '₹0.00',
  rows: [
    { date: '2025-04-01', voucher_type: 'Purchase', entry_no: 1, narration: 'Being purchase OLD', debit_paise: 0, debit_display: '₹0.00', credit_paise: 100000, credit_display: '₹1,000.00', balance_paise: -100000, balance_display: '-₹1,000.00', entry: 'e1', bill: 'b1' },
    { date: '2025-05-01', voucher_type: 'Payment', entry_no: 7, narration: 'Paid', debit_paise: 40000, debit_display: '₹400.00', credit_paise: 0, credit_display: '₹0.00', balance_paise: -60000, balance_display: '-₹600.00', entry: 'e2', bill: null },
  ],
  total_debit_paise: 40000,
  total_debit_display: '₹400.00',
  total_credit_paise: 100000,
  total_credit_display: '₹1,000.00',
  closing_paise: -60000,
  closing_display: '-₹600.00',
} as unknown as PartyStatement

function renderReport(report: Outstanding = REPORT) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Acme Traders' } as unknown as Client)
  // The screen asks for today, written DD-MM-YYYY and read back: the same ISO date.
  queryClient.setQueryData(outstanding(CLIENT, 'payables', TODAY).queryKey, report)
  queryClient.setQueryData(partyStatement(CLIENT, 'p1', FY_START, TODAY).queryKey, STATEMENT)
  render(
    <QueryClientProvider client={queryClient}>
      <OutstandingReport clientId={CLIENT} side="payables" />
    </QueryClientProvider>,
  )
}

describe('Payables', () => {
  it('lists each party with its bills aged into the right column, and what is owed in total', async () => {
    renderReport()
    const table = await screen.findByRole('table', { name: /Payables as at/ })
    const old = within(table).getByText('Purchase invoice OLD').closest('tr')!
    expect(old).toHaveTextContent('122')
    expect(old).toHaveTextContent('1,000.00')
    expect(within(table).getByText('Ravi Traders').closest('tr')).toHaveTextContent('4,700.00')
    expect(within(table).getByText(/Total \(1 party\)/).closest('tr')).toHaveTextContent('4,700.00')
  })

  it('shows money held on account or as an advance as reducing what is owed', async () => {
    renderReport()
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Held on account or as an advance').closest('tr')).toHaveTextContent('-300.00')
    expect(screen.getByText(/held on account or as advances, which lowers the total/)).toBeInTheDocument()
  })

  it('says plainly when nothing is owed', async () => {
    renderReport({ ...REPORT, parties: [], total_paise: 0, total_display: '₹0.00', on_account_paise: 0 } as unknown as Outstanding)
    expect(await screen.findByText('Nothing is outstanding to suppliers')).toBeInTheDocument()
  })

  it('opens a party’s statement of account from its name', async () => {
    renderReport()
    await userEvent.click(await screen.findByRole('button', { name: 'Ravi Traders' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Ravi Traders: statement of account')).toBeInTheDocument()
    const table = within(dialog).getByRole('table')
    expect(within(table).getByText('Purchase No. 1').closest('tr')).toHaveTextContent('1,000.00')
    expect(within(table).getByText('Payment No. 7').closest('tr')).toHaveTextContent('600.00 Cr')
    expect(within(table).getByText(/Total \(2 postings\)/).closest('tr')).toHaveTextContent('600.00 Cr')
  })
})
