import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clientDetail } from '@/api/queries/clients'
import type { Client } from '@/api/types'
import { LedgerPrint } from './LedgerPrint'

const get = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }))

const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results })

beforeEach(() => {
  get.mockReset()
  get.mockImplementation(async (url: string) => {
    if (url.includes('/ledgers/g1/rows/'))
      return page([
        { id: 'r1', value_date: '2026-04-02', narration: 'Opening sale', counterparty: 'Sunrise Traders', amount_paise: 50_000, amount_display: '500.00', is_debit: true, is_posted: true },
        { id: 'r2', value_date: '2026-04-09', narration: 'Part payment', counterparty: 'Sunrise Traders', amount_paise: 20_000, amount_display: '200.00', is_debit: false, is_posted: true },
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
