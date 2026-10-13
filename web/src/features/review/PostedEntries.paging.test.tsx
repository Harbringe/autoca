import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { journal } from '@/api/queries/books'
import { reviewSummary } from '@/api/queries/clients'
import { setAllPageSize } from '@/lib/pageSizes'
import { PostedEntries } from './PostedEntries'

vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

const CLIENT = 'c1'
const entry = (n: number) => ({
  id: `e${n}`,
  entry_date: `2026-01-${String((n % 28) + 1).padStart(2, '0')}`,
  entry_no: n,
  voucher_type: 'Payment',
  narration: `Posted entry ${n}`,
  financial_year: 2025,
  fy_label: 'FY 2025-26',
  lines: [],
})

function setup(count: number) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(journal(CLIENT).queryKey, Array.from({ length: count }, (_, i) => entry(i + 1)) as never)
  queryClient.setQueryData(reviewSummary(CLIENT).queryKey, { unresolved: 0, pending_approval: 0, total: 0 } as never)
  const root = createRootRoute()
  const page = createRoute({ getParentRoute: () => root, path: '/', component: () => <PostedEntries clientId={CLIENT} /> })
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

beforeEach(() => setAllPageSize(null))

describe('the posted entries', () => {
  it('are shown a page at a time, with the pager the other lists have', async () => {
    setup(25)
    await screen.findByText('Showing 1–10 of 25')
    expect(screen.getAllByRole('listitem').filter((li) => li.textContent?.includes('Posted entry')).length).toBe(10)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Showing 11–20 of 25')
  })

  it('follow the rows-per-page choice', async () => {
    setAllPageSize(25)
    setup(40)
    await screen.findByText('Showing 1–25 of 40')
  })

  it('show no pager when they fit on one page', async () => {
    setup(4)
    await screen.findByText('Posted entry 1')
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull()
  })
})
