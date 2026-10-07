import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MyProgressCard, PeopleCard } from './workCards'

const people = {
  period: { from: '2026-10-01', to: '2026-10-07' },
  detailed: true,
  people: [
    { member_id: 'm3', name: 'Sana Qureshi', role: 'STAFF', assigned_clients: 4, open_items: 22, finished_in_period: 17, overdue: 3, waiting_on_others: 5 },
    { member_id: 'm1', name: 'Aarav Mehta', role: 'STAFF', assigned_clients: 3, open_items: 14, finished_in_period: 38, overdue: 1, waiting_on_others: 2 },
    { member_id: 'm2', name: 'divya nair', role: 'SENIOR_CA', assigned_clients: 2, open_items: 6, finished_in_period: 52, overdue: 0, waiting_on_others: 1 },
  ],
}

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { get: vi.fn(async () => people) },
}))

const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe('the people table', () => {
  it('lists people alphabetically, ignoring case, with the five counts and no rank', async () => {
    wrap(<PeopleCard />)
    const table = await screen.findByRole('table', { name: 'What each person has on' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[0]?.textContent)).toEqual(['Aarav Mehta', 'divya nair', 'Sana Qureshi'])
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent ?? '')
    for (const wanted of ['Clients', 'Open', 'Finished', 'Late', 'Waiting on others']) expect(headers.some((h) => h.includes(wanted))).toBe(true)
    expect(headers.join(' ').toLowerCase()).not.toMatch(/rank|score|rating|top|best/)
  })
  it('says these are counts of work and not a rating of people', async () => {
    wrap(<PeopleCard />)
    expect(await screen.findByText('Counts of work, not a rating of people.')).toBeInTheDocument()
  })
})

describe("a person's own progress", () => {
  const mine = { period: { from: '', to: '' }, assigned_clients: 3, open_items: 17, overdue: 1, waiting: 4, finished_in_period: 31, daily: [], next_tasks: [], clients: [] }
  it('shows the share done from their own counts', () => {
    wrap(<MyProgressCard data={mine as never} loading={false} />)
    expect(screen.getByText('60%')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /31 finished, 17 still open and 4 waiting on others: 60% done/ })).toBeInTheDocument()
  })
  it('says there is nothing to measure when no work is assigned', () => {
    wrap(<MyProgressCard data={{ ...mine, open_items: 0, waiting: 0, finished_in_period: 0 } as never} loading={false} />)
    expect(screen.getByText(/nothing to measure/i)).toBeInTheDocument()
  })
})
