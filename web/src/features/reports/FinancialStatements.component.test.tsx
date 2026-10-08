import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { FinancialStatements } from './FinancialStatements'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))
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
  notes: [{ number: 9, title: 'Trade payables', rows: [{ label: 'Ravi Traders', ledger: 'l1', current_paise: 1000000, previous_paise: 500000 }], total_current_paise: 1000000, total_previous_paise: 500000 }],
  regroupings: [{ ledger: 'l2', name: 'Related Party', previous_line: 'CA.LOANS', current_line: 'CL.PAY', previous_paise: 800000, current_paise: -300000, text: '' }],
  footer,
  has_previous: true,
  balances: true,
  suspense_paise: 0,
}

function renderIt() {
  vi.mocked(raw.get).mockResolvedValue(STATEMENTS)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FinancialStatements clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

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
    expect(await screen.findByRole('heading', { name: /Note 9 · Trade payables/ })).toBeInTheDocument()
    expect(screen.getByText('Ravi Traders')).toBeInTheDocument()
    expect(screen.getByText('Regrouping of previous year figures')).toBeInTheDocument()
    expect(screen.getByText(/last year shown under Short term loans and advances/)).toBeInTheDocument()
  })
})
