import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clientDetail } from '@/api/queries/clients'
import type { Client } from '@/api/types'
import { LedgerPrint } from './LedgerPrint'

const get = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }))

const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results })
const entry = (id: string, date: string, no: number, narration: string, lines: [string, string, 'DR' | 'CR', number][]) => ({
  id,
  entry_date: date,
  entry_no: no,
  voucher_number: `S/${no}`,
  narration,
  is_superseded: false,
  lines: lines.map(([ledger_account, ledger_name, direction, amount_paise], i) => ({ id: `${id}-${i}`, ledger_account, ledger_name, direction, amount_paise })),
})

beforeEach(() => {
  get.mockReset()
  get.mockImplementation(async (url: string) => {
    if (url.includes('/journal-entries/'))
      return page([
        entry('e1', '2026-04-02', 1, 'Opening sale', [['g1', 'Sunrise Traders', 'DR', 50_000], ['s1', 'Sales', 'CR', 50_000]]),
        entry('e2', '2026-04-09', 2, 'Part payment', [['b1', 'HDFC', 'DR', 20_000], ['g1', 'Sunrise Traders', 'CR', 20_000]]),
        entry('e3', '2026-04-10', 3, 'Not ours', [['s1', 'Sales', 'CR', 9_000], ['b1', 'HDFC', 'DR', 9_000]]),
      ])
    if (url.includes('/ledgers/')) return page([{ id: 'g1', name: 'Sunrise Traders' }])
    if (url.includes('/gst/registrations/')) return { results: [] }
    throw new Error(`unexpected ${url}`)
  })
})

describe('LedgerPrint', () => {
  it('prints the ledger with a running balance', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Acme Trading' } as unknown as Client)
    render(
      <QueryClientProvider client={queryClient}>
        <LedgerPrint clientId="c1" ledgerId="g1" />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Opening sale')).toBeInTheDocument()
    expect(screen.getByText('Part payment')).toBeInTheDocument()
    expect(screen.getAllByText('300.00 Dr')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: /Sunrise Traders/ })).toBeInTheDocument()
  })
})
