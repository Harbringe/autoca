import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { partyCandidates } from '@/api/queries/bills'
import { setAllPageSize } from '@/lib/pageSizes'
import { PartiesFound } from './PartiesFound'

const post = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

const cand = (name: string, n: number) => ({ name, count: n, first: '2025-04-01', last: '2025-05-01', paid_paise: 100, paid_display: '₹1.00', received_paise: 0, received_display: '', suggested_role: 'VENDOR' })

function setup(names: string[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(partyCandidates('c1', false).queryKey, { candidates: names.map((n, i) => cand(n, 5 + i)) } as never)
  render(
    <QueryClientProvider client={queryClient}>
      <PartiesFound clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  setAllPageSize(10)
  post.mockReset()
  post.mockResolvedValue({ created: 12 })
})

describe('the parties found in the statements', () => {
  it('can all be ticked at once, across pages, and unticked again', async () => {
    const user = userEvent.setup()
    setup(Array.from({ length: 12 }, (_, i) => `Party ${i + 1}`))
    expect(await screen.findByRole('button', { name: 'Create 0 parties' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: 'Select all 12' }))
    // twelve are chosen though only ten are on the page
    expect(screen.getByRole('button', { name: 'Create 12 parties' })).toBeEnabled()
    expect(screen.getByText('12 selected')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Select all 12' }))
    expect(screen.getByRole('button', { name: 'Create 0 parties' })).toBeDisabled()
  })

  it('creates every one that was ticked, each with its role', async () => {
    const user = userEvent.setup()
    setup(['Ravi', 'Mehta'])
    await user.click(await screen.findByRole('checkbox', { name: 'Select all 2' }))
    await user.click(screen.getByRole('button', { name: 'Create 2 parties' }))
    expect(post).toHaveBeenCalled()
    expect(post.mock.calls[0]![1]).toMatchObject({ parties: [{ name: 'Ravi', role: 'VENDOR' }, { name: 'Mehta', role: 'VENDOR' }] })
  })
})
