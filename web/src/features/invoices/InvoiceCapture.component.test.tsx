import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import type { InvoiceReading } from '@/api/types'
import { InvoiceCapture } from './InvoiceCapture'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))

const READING = {
  id: 'r1',
  kind: 'PURCHASE',
  status: 'OPEN',
  status_display: 'Waiting for a person',
  document: 'd1',
  filename: 'ravi-042.pdf',
  proved: true,
  unreadable_reason: '',
  attention: '',
  auto_booked: false,
  checks: [{ name: 'arithmetic', ok: true, detail: '' }],
  created_at: '2025-08-13T10:00:00Z',
  suggested_party: null,
  matching_bill: null,
  bill: null,
  payments: [],
  read: {
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
  },
} as unknown as InvoiceReading

function Harness() {
  const [reading, setReading] = useState<InvoiceReading | null>(null)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <InvoiceCapture clientId="c1" reading={reading} onReading={setReading} onBooked={() => {}} />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.mocked(raw.get).mockImplementation(async (path: string) => {
    if (path.includes('/preview/')) return { pages: 2, filename: 'ravi-042.pdf' }
    return { results: [], next: null }
  })
})

describe('capturing an invoice', () => {
  it('asks for a file, with the form waiting beside it', () => {
    render(<Harness />)
    expect(screen.getByText('Drop an invoice here, or click to choose')).toBeInTheDocument()
    expect(screen.getByText(/details fill in here/)).toBeInTheDocument()
  })

  it('shows the file as pages and fills the form in from what was read, asking the server not to book it', async () => {
    let finish: (r: InvoiceReading) => void = () => {}
    vi.mocked(raw.post).mockImplementation(() => new Promise((resolve) => (finish = resolve as never)))
    render(<Harness />)

    await userEvent.upload(screen.getByLabelText('Choose an invoice file'), new File(['%PDF-1.4'], 'ravi-042.pdf', { type: 'application/pdf' }))
    expect(await screen.findByText('Reading ravi-042.pdf…')).toBeInTheDocument()
    finish(READING)

    expect(await screen.findByAltText('Page 1 of 2 of the uploaded file')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('RT/042')).toBeInTheDocument()
    expect(screen.getByDisplayValue('12-08-2025')).toBeInTheDocument()
    const form = vi.mocked(raw.post).mock.calls[0]![1] as FormData
    expect(form.get('book')).toBe('false')
  })

  it('turns pages and says what could not be read when the figures do not add up', async () => {
    vi.mocked(raw.post).mockResolvedValue({
      ...READING,
      proved: false,
      checks: [{ name: 'arithmetic', ok: false, detail: 'Taxable value plus tax does not equal the total.' }],
    })
    render(<Harness />)

    await userEvent.upload(screen.getByLabelText('Choose an invoice file'), new File(['%PDF-1.4'], 'ravi-042.pdf', { type: 'application/pdf' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Next page' }))

    await waitFor(() => expect(screen.getByAltText('Page 2 of 2 of the uploaded file')).toBeInTheDocument())
    expect(screen.getByText(/does not equal the total/)).toBeInTheDocument()
  })

  it('refuses a kind of file that cannot be read before sending it', async () => {
    render(<Harness />)
    await userEvent.upload(screen.getByLabelText('Choose an invoice file'), new File(['MZ'], 'macro.exe'), { applyAccept: false })
    expect(raw.post).not.toHaveBeenCalled()
  })
})
