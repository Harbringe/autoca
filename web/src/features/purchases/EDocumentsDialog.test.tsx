import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { EDocumentsDialog } from './EDocumentsDialog'

vi.mock('@/api/client', () => ({ raw: { post: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const saveFile = vi.fn()
vi.mock('@/platform/download', () => ({ saveFile: (...a: unknown[]) => saveFile(...a) }))

const DRAFT = {
  eligible: true,
  note: 'E-invoicing applies to a taxpayer whose aggregate turnover has been over Rs 5 crore.',
  e_invoice: { json: { Version: '1.1' }, missing: ["Mehta Stores's address and pincode."] },
  eway_bill: { json: { version: '1.0.0621' }, missing: ['The distance in km.'], required: true },
}

function show(body: object = DRAFT) {
  vi.mocked(raw.post).mockResolvedValue(body)
  render(
    <QueryClientProvider client={new QueryClient()}>
      <EDocumentsDialog clientId="c1" billId="b1" reference="S-1" onClose={() => undefined} />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('EDocumentsDialog', () => {
  it('lists what is missing, refreshes with the details given, and downloads each file', async () => {
    show()
    expect(await screen.findByText("Mehta Stores's address and pincode.")).toBeInTheDocument()
    expect(screen.getByText('needed: the invoice is over ₹50,000')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Buyer pincode'), '400001')
    await userEvent.type(screen.getByLabelText('Distance (km)'), '150')
    await userEvent.click(screen.getByRole('button', { name: 'Update the draft' }))
    await waitFor(() => expect(raw.post).toHaveBeenLastCalledWith('/api/v1/clients/c1/bills/b1/e-documents/', { buyer_pin: '400001', distance_km: 150 }))
    await userEvent.click(screen.getByRole('button', { name: 'Download E-invoice JSON' }))
    await waitFor(() => expect(saveFile).toHaveBeenCalledWith('e-invoice-S-1.json', expect.any(Blob)))
  })

  it('says so when the document is not one that needs an e-invoice', async () => {
    show({ eligible: false, note: 'E-invoices and e-way bills are for sales invoices, credit notes and debit notes.', e_invoice: null, eway_bill: null })
    expect(await screen.findByText(/are for sales invoices/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Download/ })).not.toBeInTheDocument()
  })
})
