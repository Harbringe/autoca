import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { firmOverview } from '@/api/queries/overview'
import { ClientPipeline } from './ClientPipeline'

vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@/features/clients/ClientTeamScreen', () => ({ People: () => <div>People block</div> }))
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

function renderIt(client: Record<string, unknown>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(firmOverview().queryKey, { clients: [{ id: 'c1', name: 'Divine', lead: { id: 'u', name: 'owner_rudra' }, signed_off_through: null, ...client }], by_stage: {} } as never)
  render(
    <QueryClientProvider client={queryClient}>
      <ClientPipeline clientId="c1" />
    </QueryClientProvider>,
  )
}

describe('the client pipeline', () => {
  it('marks the stage the books are at, ticks the ones before it, and links the next step', async () => {
    renderIt({ stage: 'needs_ledger', next_step: { code: 'place', label: '6 rows need a ledger', count: 6 } })
    const track = await screen.findByRole('list', { name: /step 2 of 6/ })
    const items = within(track).getAllByRole('listitem')
    expect(items).toHaveLength(6)
    expect(items[1]).toHaveAttribute('aria-current', 'step')
    expect(within(items[0]!).getByText(/\(done\)/)).toBeInTheDocument()
    expect(screen.getByText('6 rows need a ledger')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sort entries' })).toHaveAttribute('href', '/clients/$clientId/review')
    expect(screen.getByText('People block')).toBeInTheDocument()
  })

  it('has no button when nothing is left to do', async () => {
    renderIt({ stage: 'signed_off', next_step: { code: 'none', label: 'Nothing left to do', count: 0 } })
    expect(await screen.findByText('Nothing left to do')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /entries|statement|review/i })).toBeNull()
  })
})
