import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { invoiceReadings, openItems } from '@/api/queries/bills'
import { bankAccounts, clientDetail, reviewSummary } from '@/api/queries/clients'
import type { Client, InvoiceReading } from '@/api/types'
import { ClientProfileScreen } from './ClientProfileScreen'

vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
// The year's figures read the financial year from the address bar; they are tested on their own.
vi.mock('./OverviewReports', () => ({ OverviewReports: () => null }))
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

function renderIt(summary: Record<string, number>, fixes: number, open: number) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Laxmi', fy_start: '2026-04-01', lead: null, business_profile: '' } as unknown as Client)
  queryClient.setQueryData(bankAccounts('c1').queryKey, { count: 1, results: [] } as never)
  queryClient.setQueryData(reviewSummary('c1').queryKey, summary as never)
  queryClient.setQueryData(openItems('c1').queryKey, { count: fixes, items: [], kinds: [] } as never)
  queryClient.setQueryData(
    invoiceReadings('c1').queryKey,
    Array.from({ length: open }, (_, i) => ({ id: `r${i}`, status: 'OPEN' }) as unknown as InvoiceReading),
  )
  render(
    <QueryClientProvider client={queryClient}>
      <ClientProfileScreen clientId="c1" />
    </QueryClientProvider>,
  )
}

describe('the client overview', () => {
  it('counts what is waiting, each card the screen where it is done', async () => {
    renderIt({ unresolved: 31, pending: 40, pending_approval: 40 }, 4, 2)
    const heading = await screen.findByRole('heading', { name: 'What needs you' })
    const section = heading.closest('section')!
    expect(within(section).getByText('entries to sort into accounts')).toBeInTheDocument()
    expect(within(section).getByText('31')).toBeInTheDocument()
    expect(within(section).getByText('sorted entries ready to record')).toBeInTheDocument()
    expect(within(section).getByText('40')).toBeInTheDocument()
    expect(within(section).getByText('invoices waiting to be booked')).toBeInTheDocument()
    expect(within(section).getByText('items that do not tie out')).toBeInTheDocument()
    expect(within(section).getAllByRole('link')).toHaveLength(4)
  })

  it('leads with one sentence naming the work in order', async () => {
    renderIt({ unresolved: 6, pending_approval: 6 }, 0, 0)
    expect(await screen.findByText('12 items need you: sort 6, then record 6.')).toBeInTheDocument()
  })

  it('says nothing is waiting, and where to go next, when it is clear', async () => {
    renderIt({ unresolved: 0, pending_approval: 0 }, 0, 0)
    expect(await screen.findByText(/Nothing is waiting on this client\. Upload/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Bank statements' })).toBeInTheDocument()
  })

  it('shows the profile as a strip, with the GSTIN gap flagged', async () => {
    renderIt({ unresolved: 0, pending_approval: 0 }, 0, 0)
    expect(await screen.findByText('Senior CA')).toBeInTheDocument()
    expect(screen.getByText('Year starts')).toBeInTheDocument()
  })
})
