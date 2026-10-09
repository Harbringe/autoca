import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { FinancialStatements } from './FinancialStatements'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, ...rest }: { children: React.ReactNode }) => <a {...(rest as object)}>{children}</a>,
}))

const footer = { client_name: 'Divine Construwell', financial_year: 2025, period_start: '2025-04-01', period_end: '2026-03-31', entry_count: 5, pending_review: 0, generated_at: '2026-10-08T10:00:00Z', fy_label: '2025-26', is_complete: true }

const STATEMENTS = {
  balance_sheet: [
    { key: 'h.I', label: "I. OWNERS' FUNDS AND LIABILITIES", kind: 'heading', level: 0, note: null, current_paise: null, previous_paise: null },
    { key: 'CL.PAY', label: 'Trade payables', kind: 'line', level: 2, note: 9, current_paise: 1000000, previous_paise: 500000 },
    { key: 't.L', label: 'TOTAL', kind: 'total', level: 0, note: null, current_paise: 1000000, previous_paise: 500000 },
  ],
  profit_and_loss: [{ key: 'PL.REV', label: 'Revenue from operations', kind: 'line', level: 0, note: 19, current_paise: -250000, previous_paise: 0 }],
  notes: [{ number: 9, title: 'Trade payables', rows: [{ label: 'Ravi Traders', ledger: 'l1', current_paise: 1000000, previous_paise: 500000, section: '', guessed: false }], choices: [], total_current_paise: 1000000, total_previous_paise: 500000 }],
  regroupings: [{ ledger: 'l2', name: 'Related Party', previous_line: 'CA.LOANS', current_line: 'CL.PAY', previous_paise: 800000, current_paise: -300000, text: '' }],
  footer,
  has_previous: true,
  balances: true,
  suspense_paise: 0,
  unit_paise: 100,
  unit_label: 'Rs.',
  about: 'A trading firm in Pune.',
  policies: '',
  capital: {
    rows: [{ name: 'Asha', share_bp: 6000, opening_paise: 0, introduced_paise: 300000, remuneration_paise: 0, interest_paise: 0, withdrawals_paise: 0, profit_share_paise: -150000, closing_paise: 150000 }],
    previous: [],
    owners_funds_paise: 150000,
    difference_paise: 0,
  },
  warnings: ['Closing stock for this year is not entered.'],
  schedules: [
    {
      note: 9,
      title: 'Trade payables by kind of supplier',
      columns: ['31 March 2026', '31 March 2025'],
      rows: [
        { label: '(a) Total outstanding dues of micro, small and medium enterprises', values: [400000, 0], kind: 'line' },
        { label: 'Total trade payables', values: [1000000, 500000], kind: 'total' },
      ],
    },
  ],
  entity_type: 'partnership',
  size: 'msme',
  size_suggested: 'msme',
  size_reason: '',
  size_statement: 'The entity is a Micro, Small and Medium Sized Entity (MSME).',
  capital_title: "Partners' Capital Accounts",
  cash_flow: [
    { key: 'A', label: 'A. Cash flow from operating activities', kind: 'heading', level: 0, note: null, current_paise: null, previous_paise: null },
    { key: 'A.pbt', label: 'Net profit before tax', kind: 'line', level: 2, note: null, current_paise: 1200000, previous_paise: 800000 },
    { key: 'A.net', label: 'Net cash flow from operating activities (A)', kind: 'total', level: 0, note: null, current_paise: 1000000, previous_paise: -250000 },
    { key: 'N.diff', label: 'Difference the books do not explain', kind: 'line', level: 1, note: null, current_paise: 5000, previous_paise: 0 },
  ],
}

function renderIt() {
  vi.mocked(raw.get).mockResolvedValue(STATEMENTS)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FinancialStatements clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

describe('the Cash Flow Statement', () => {
  it('is shown for a Large entity, with brackets for cash going out and any difference visible', async () => {
    vi.mocked(raw.get).mockResolvedValue({ ...STATEMENTS, size: 'large' })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <FinancialStatements clientId="c1" fy={2025} />
      </QueryClientProvider>,
    )
    const cf = await screen.findByRole('table', { name: 'Cash Flow Statement' })
    expect(within(cf).getByText('A. Cash flow from operating activities')).toBeInTheDocument()
    expect(within(cf).getByText('(2,500.00)')).toBeInTheDocument()
    expect(within(cf).getByText('Difference the books do not explain')).toBeInTheDocument()
  })

  it('is left out for an MSME, which is exempt, and says why', async () => {
    renderIt()
    await screen.findByRole('table', { name: 'Balance Sheet' })
    expect(screen.queryByRole('table', { name: 'Cash Flow Statement' })).not.toBeInTheDocument()
    expect(screen.getByText(/required only of a Large entity/)).toBeInTheDocument()
  })
})

describe('the ICAI-format statements', () => {
  it('shows the current and previous year, a note number on each line, and brackets for a negative', async () => {
    renderIt()
    const bs = await screen.findByRole('table', { name: 'Balance Sheet' })
    expect(within(bs).getByText('31 March 2026')).toBeInTheDocument()
    expect(within(bs).getByText('31 March 2025')).toBeInTheDocument()
    const payables = within(bs).getByText('Trade payables').closest('tr')!
    expect(within(payables).getByLabelText('Note 9')).toHaveAttribute('href', '#note-9')
    expect(within(payables).getByText('10,000.00')).toBeInTheDocument()
    const pl = screen.getByRole('table', { name: 'Statement of Profit and Loss' })
    expect(within(pl).getByText('(2,500.00)')).toBeInTheDocument()
  })

  it('takes each figure apart in its note, and lists a ledger that moved between lines', async () => {
    renderIt()
    expect(await screen.findByRole('heading', { name: 'Note 9 · Trade payables' })).toBeInTheDocument()
    expect(screen.getByText('Ravi Traders')).toBeInTheDocument()
    expect(screen.getByText('Regrouping of previous year figures')).toBeInTheDocument()
    expect(screen.getByText(/last year shown under Short term loans and advances/)).toBeInTheDocument()
  })

  it('writes Notes 1 and 2, tables the partners, and lists what is still to settle', async () => {
    renderIt()
    expect(await screen.findByText('A trading firm in Pune.')).toBeInTheDocument()
    expect(screen.getAllByText('Not written yet.')).toHaveLength(1) // Note 2
    expect(screen.getByRole('heading', { name: /Note 3 · Partners' Capital Accounts, partner by partner/ })).toBeInTheDocument()
    const capital = screen.getByRole('heading', { name: /partner by partner/ }).closest('article')!
    expect(within(capital).getByText('Asha')).toBeInTheDocument()
    expect(within(capital).getAllByText('(1,500.00)').length).toBeGreaterThan(0)
    expect(screen.getByRole('list', { name: 'To settle before issuing' })).toHaveTextContent('Closing stock for this year is not entered.')
  })

  it('offers the Excel file for this year, and the details form', async () => {
    renderIt()
    const link = await screen.findByRole('link', { name: /Download Excel/ })
    expect(link).toHaveAttribute('href', expect.stringContaining('/clients/c1/reports/financial-statements/export/?fy=2025'))
    vi.mocked(raw.get).mockImplementation(async (path: string) => (path.includes('/settings/') ? { about: '', policies: '', rounding: 'rupees', years: {} } : STATEMENTS))
    await userEvent.click(screen.getByRole('button', { name: /Statement details/ }))
    expect(await screen.findByLabelText(/Closing stock at 31 March 2026/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add a partner/ })).toBeInTheDocument()
  })

  it('shows the tables that belong to a note and the entity size under Note 2', async () => {
    renderIt()
    const table = await screen.findByRole('article', { name: 'Trade payables by kind of supplier' })
    expect(within(table).getByText('(a) Total outstanding dues of micro, small and medium enterprises')).toBeInTheDocument()
    expect(within(table).getByText('4,000.00')).toBeInTheDocument()
    expect(screen.getByText('The entity is a Micro, Small and Medium Sized Entity (MSME).')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Note 3 · Partners' Capital Accounts, partner by partner/ })).toBeInTheDocument()
  })

  it('shows the figures in the unit they were rounded to', async () => {
    vi.mocked(raw.get).mockResolvedValue({
      ...STATEMENTS,
      unit_paise: 10_000_000,
      unit_label: 'Rs. in lakhs',
      balance_sheet: [{ key: 'CL.PAY', label: 'Trade payables', kind: 'line', level: 2, note: 9, current_paise: 250_000_000, previous_paise: 0 }],
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <FinancialStatements clientId="c1" fy={2025} />
      </QueryClientProvider>,
    )
    const bs = await screen.findByRole('table', { name: 'Balance Sheet' })
    expect(within(bs).getByText('25.00')).toBeInTheDocument()
    expect(screen.getAllByText('(Amount in Rs. in lakhs)').length).toBeGreaterThan(0)
  })

  it('groups a note under its sub-heads', async () => {
    vi.mocked(raw.get).mockResolvedValue({
      ...STATEMENTS,
      notes: [
        {
          number: 19,
          title: 'Revenue from operations',
          rows: [
            { label: 'Sales', ledger: 'a', current_paise: 100, previous_paise: 0, section: 'Sale of products', guessed: false },
            { label: 'Consulting', ledger: 'b', current_paise: 50, previous_paise: 0, section: 'Sale of services', guessed: true },
          ],
          choices: ['Sale of products', 'Sale of services', 'Other operating revenue'],
          total_current_paise: 150,
          total_previous_paise: 0,
        },
      ],
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <FinancialStatements clientId="c1" fy={2025} />
      </QueryClientProvider>,
    )
    expect((await screen.findAllByText('Sale of products')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Sale of services').length).toBeGreaterThan(0)
    // only the ledger that fell to a catch-all asks to be placed
    expect(screen.getAllByRole('combobox', { name: /Sub-head for/ })).toHaveLength(1)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Sub-head for Consulting' }), 'Other operating revenue')
    expect(raw.patch).toHaveBeenCalledWith(expect.stringContaining('/ledgers/b/'), { nce_section: 'Other operating revenue' })
  })
})
