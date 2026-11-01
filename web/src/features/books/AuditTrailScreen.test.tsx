import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuditTrailScreen } from './AuditTrailScreen'

const get = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }))

const row = (over: Record<string, unknown> = {}) => ({
  id: 'a1',
  at: '2026-11-01T10:30:00Z',
  kind: 'LEDGER',
  action: 'EDITED',
  action_display: 'Changed',
  label: 'Misc Costs 2',
  actor_name: 'Asha Rao',
  note: '',
  before: { name: 'Misc Costs', group: 'INDIRECT_EXPENSE' },
  after: { name: 'Misc Costs 2', group: 'INDIRECT_EXPENSE' },
  ...over,
})

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <AuditTrailScreen clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue({ count: 2, results: [row(), row({ id: 'a2', kind: 'ENTRY', action: 'REMOVED', action_display: 'Entry removed', label: 'Sales no. 4, 05-04-2025', before: { narration: 'old' }, after: {}, note: 'duplicate' })] })
})

describe('AuditTrailScreen', () => {
  it('lists each change with who made it and what it was about', async () => {
    renderScreen()
    const list = await screen.findByRole('list', { name: 'Changes' })
    expect(within(list).getByText(/Misc Costs 2/)).toBeInTheDocument()
    expect(within(list).getAllByText(/Asha Rao/)).toHaveLength(2)
    expect(within(list).getByText(/Sales no\. 4/)).toBeInTheDocument()
    expect(within(list).getByText(/duplicate/)).toBeInTheDocument()
  })

  it('shows only the fields that changed, before and after', async () => {
    const user = userEvent.setup()
    renderScreen()
    await user.click(await screen.findByRole('button', { name: /Show what changed.*Misc Costs 2/ }))
    const diff = await screen.findByTestId('diff-a1')
    expect(diff).toHaveTextContent('name')
    expect(diff).toHaveTextContent('Misc Costs')
    expect(diff).toHaveTextContent('Misc Costs 2')
    expect(diff).not.toHaveTextContent('group')
  })

  it('asks the server for one kind of change at a time', async () => {
    renderScreen()
    await screen.findByRole('list', { name: 'Changes' })
    fireEvent.change(screen.getByLabelText('Kind of change'), { target: { value: 'LEDGER' } })
    await waitFor(() => expect(get).toHaveBeenLastCalledWith(expect.stringContaining('kind=LEDGER')))
  })

  it('searches the text of the changes', async () => {
    const user = userEvent.setup()
    renderScreen()
    await screen.findByRole('list', { name: 'Changes' })
    await user.type(screen.getByLabelText('Search the changes'), 'Costs')
    await waitFor(() => expect(get).toHaveBeenLastCalledWith(expect.stringContaining('q=Costs')))
  })

  it('pages through a long trail', async () => {
    get.mockResolvedValue({ count: 120, results: [row()] })
    const user = userEvent.setup()
    renderScreen()
    await screen.findByRole('list', { name: 'Changes' })
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(get).toHaveBeenLastCalledWith(expect.stringContaining('offset=50')))
  })

  it('says so when nothing has been changed', async () => {
    get.mockResolvedValue({ count: 0, results: [] })
    renderScreen()
    expect(await screen.findByText(/Nothing has been changed/)).toBeInTheDocument()
  })
})
