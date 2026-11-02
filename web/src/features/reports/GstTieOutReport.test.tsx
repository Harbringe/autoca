import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { GstTieOutReport } from './GstTieOutReport'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))

function show(body: object) {
  vi.mocked(raw.get).mockResolvedValue(body)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <GstTieOutReport clientId="c1" fy={2025} />
    </QueryClientProvider>,
  )
}

describe('GstTieOutReport', () => {
  it('shows each head and says where the books differ', async () => {
    show({
      fy: 2025,
      agrees: false,
      heads: [{ side: 'input', head: 'CGST', invoices_paise: 900000, books_paise: 1000000, difference_paise: 100000 }],
      months: [{ month: '2025-10', outward_taxable_paise: 0, inward_taxable_paise: 10000000, input_cgst_paise: 900000 }],
      net: { output_paise: 0, input_paise: 900000, payable_paise: -900000 },
    })
    expect(await screen.findByText(/do not carry what the invoices say/)).toBeInTheDocument()
    expect(screen.getByText('Input CGST')).toBeInTheDocument()
    expect(screen.getByText('Oct')).toBeInTheDocument()
    expect(screen.getByText('Carried forward as credit')).toBeInTheDocument()
  })

  it('says so when there is nothing yet', async () => {
    show({ fy: 2025, agrees: true, heads: [], months: [], net: { output_paise: 0, input_paise: 0, payable_paise: 0 } })
    expect(await screen.findByText(/No sales or purchase invoices/)).toBeInTheDocument()
  })
})
