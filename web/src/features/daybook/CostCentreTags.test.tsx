import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { costCentres } from '@/api/queries/analysis'
import type { JournalEntry } from '@/api/types'
import { CostCentreTags } from './CostCentreTags'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const entry = {
  id: 'e1',
  lines: [
    { id: 'a', ledger_name: 'Contract Work', ledger_group: 'DIRECT_EXPENSE', direction: 'DR', amount_paise: 1000000 },
    { id: 'b', ledger_name: 'Vendor', ledger_group: 'CREDITOR', direction: 'CR', amount_paise: 1000000 },
  ],
} as unknown as JournalEntry

function show(centres: { id: string; name: string }[]) {
  vi.mocked(raw.get).mockResolvedValue([])
  vi.mocked(raw.post).mockResolvedValue([])
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(costCentres('c1').queryKey, centres)
  render(
    <QueryClientProvider client={qc}>
      <CostCentreTags clientId="c1" entry={entry} mayTag />
    </QueryClientProvider>,
  )
}

describe('CostCentreTags', () => {
  it('offers only income and expense lines and tags the whole line to the chosen centre', async () => {
    show([{ id: 'k1', name: 'Pune Site' }])
    expect(screen.queryByLabelText('Cost centre for Vendor')).not.toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Cost centre for Contract Work'), 'Pune Site')
    await waitFor(() =>
      expect(raw.post).toHaveBeenCalledWith('/api/v1/clients/c1/cost-centre-tags/', { line: 'a', allocations: [{ cost_centre: 'k1', amount_paise: 1000000 }] }),
    )
  })

  it('shows nothing when the client has no cost centres', () => {
    show([])
    expect(screen.queryByLabelText('Cost centres')).not.toBeInTheDocument()
  })
})
