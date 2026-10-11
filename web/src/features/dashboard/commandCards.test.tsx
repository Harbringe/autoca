import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Portfolio } from '@/api/types'
import { PersonCard, PersonCards, personStatus } from '@/features/work/PersonCards'
import { ActivityCard, friendlyAction, HealthCard, OwnerStrip, PipelineCard, PriorityCard, StaffListCard, WorkColumnsCard } from './commandCards'

vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true, me: { permissions: [] } }) }))

type Handler = (path: string) => unknown
let handler: Handler = () => ({})
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { get: vi.fn(async (path: string) => handler(path)) },
}))

const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const TODAY = new Date(2026, 9, 11)
const client = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  lead: { id: 'l1', name: 'Lead One' },
  stage: 'needs_ledger',
  next_step: { code: 'place', label: '', count: 1 },
  unresolved: 0,
  pending_approval: 0,
  assistant_waiting: 0,
  ai_unchecked: 0,
  review_pending: false,
  signed_off_through: null,
  last_statement_end: null,
  months_missing: [],
  detail: true,
  health: 'on_track',
  ...extra,
})
const portfolio = (clients: unknown[], extra: Record<string, unknown> = {}) =>
  ({
    totals: { clients: clients.length, unresolved: 0, pending_approval: 0, assistant_waiting: 0, ai_unchecked: 0, review_pending: 0, months_missing: 0 },
    by_stage: { no_statements: 0, needs_ledger: 0, ready_to_post: 0, ready_for_review: 0, in_review: 0, signed_off: 0 },
    clients,
    attention: [],
    deadlines: [],
    detailed: true,
    ...extra,
  }) as unknown as Portfolio

beforeEach(() => {
  handler = () => ({})
})

describe('the owner strip', () => {
  it('shows six tiles with the shared definitions and keeps books in review apart from work waiting', async () => {
    handler = () => ({ period: { from: '2026-07-20', to: '2026-10-11' }, scope: 'firm', weekly: [], totals: { received: 0, finished: 0, prev_received: 0, prev_finished: 0 } })
    const data = portfolio([client('a', 'Client A', { unresolved: 4, pending_approval: 2, ai_unchecked: 1, seal_due: '2026-09-30' }), client('b', 'Client B')], {
      totals: { clients: 2, unresolved: 4, pending_approval: 2, assistant_waiting: 0, ai_unchecked: 1, review_pending: 3, months_missing: 0 },
    })
    wrap(<OwnerStrip data={data} state="ready" today={TODAY} />)
    expect(screen.getByText('Work waiting').closest('a')).toHaveTextContent('7')
    expect(screen.getByText('Books in review').closest('a')).toHaveTextContent('3')
    expect(screen.getByText('Late').closest('a')).toHaveTextContent('1')
    expect(screen.getByText('Late').closest('a')).toHaveTextContent('of 2')
  })
  it('shows skeleton tiles while the portfolio loads', () => {
    wrap(<OwnerStrip data={undefined} state="loading" today={TODAY} />)
    expect(screen.getAllByText(/^Loading:/).length).toBeGreaterThanOrEqual(5)
  })
})

describe('the pipeline card', () => {
  it('writes the count of each stage and the total as an accessible headline', () => {
    const data = portfolio([client('a', 'A')], { by_stage: { no_statements: 0, needs_ledger: 1, ready_to_post: 2, ready_for_review: 0, in_review: 0, signed_off: 4 } })
    wrap(<PipelineCard data={data} state="ready" />)
    expect(screen.getByRole('img', { name: '7 clients by stage of their books' })).toBeInTheDocument()
  })
  it('says what fills it when there are no clients, and has a skeleton while loading', () => {
    const { rerender } = wrap(<PipelineCard data={portfolio([])} state="ready" />)
    expect(screen.getByText(/No clients yet/)).toBeInTheDocument()
    rerender(<QueryClientProvider client={new QueryClient()}><PipelineCard data={undefined} state="loading" /></QueryClientProvider>)
    expect(screen.getByText(/Loading: Where are my clients/)).toBeInTheDocument()
  })
})

describe('the health card', () => {
  it('counts clients by the owner definitions: late, at risk, on track', () => {
    const data = portfolio([client('a', 'A', { seal_due: '2026-09-30' }), client('b', 'B', { months_missing: ['2026-07'] }), client('c', 'C')])
    wrap(<HealthCard data={data} state="ready" today={TODAY} />)
    expect(screen.getByRole('img', { name: '1 of 3 clients on track, 1 at risk, 1 late' })).toBeInTheDocument()
  })
})

describe('the work columns card', () => {
  it('draws one column per client with work, biggest first, and links to where it is done', () => {
    const data = portfolio([client('a', 'Client A', { unresolved: 2 }), client('b', 'Client B', { unresolved: 5, pending_approval: 1 }), client('c', 'Client C')])
    wrap(<WorkColumnsCard data={data} state="ready" />)
    const table = screen.getByRole('table', { name: 'Entries waiting, by client and kind' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Client B')
    expect(rows).toHaveLength(2)
  })
  it('says so when nothing is waiting', () => {
    wrap(<WorkColumnsCard data={portfolio([client('a', 'A')])} state="ready" />)
    expect(screen.getByText('No entry is waiting on any client.')).toBeInTheDocument()
  })
})

describe('the priority card', () => {
  const item = (severity: string, text: string) => ({ severity, kind: 'k', client: 'a', client_name: 'Client A', text, to: '/clients/a/review', search: {}, amount_paise: null })
  it('gives what, which client, who leads it and when it is due, with a word as well as a colour', () => {
    const data = portfolio([client('a', 'Client A')], {
      attention: [item('critical', 'TDS is overdue'), item('medium', 'Rows to sort')],
      deadlines: [{ date: '2026-10-20', label: 'Seal the books', clients: ['Client A'] }],
    })
    wrap(<PriorityCard data={data} state="ready" today={TODAY} />)
    const row = screen.getByText('TDS is overdue').closest('a')!
    expect(row).toHaveTextContent('Client A')
    expect(row).toHaveTextContent('Lead One')
    expect(row).toHaveTextContent('Seal the books 20-10-2026')
    expect(row).toHaveTextContent('Late')
  })
  it('shows our standing of the client, not the server severity word', () => {
    const data = portfolio([client('a', 'Client A', { seal_due: '2026-09-30' })], { attention: [item('medium', 'Rows to sort')] })
    wrap(<PriorityCard data={data} state="ready" today={TODAY} />)
    const row = screen.getByText('Rows to sort').closest('a')!
    expect(row).toHaveTextContent('Late')
    expect(row).toHaveTextContent('Seal date passed')
  })
  it('is calm when nothing needs attention', () => {
    wrap(<PriorityCard data={portfolio([client('a', 'A')])} state="ready" today={TODAY} />)
    expect(screen.getByText('Nothing needs attention. Good.')).toBeInTheDocument()
  })
})

const person = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  member_id: id,
  name,
  role: 'STAFF',
  assigned_clients: 2,
  open_items: 6,
  finished_in_period: 4,
  overdue: 0,
  waiting_on_others: 1,
  ...extra,
})

describe('the staff list card', () => {
  it('lists people in name order with initials, a share finished and a bar named for a screen reader', async () => {
    handler = () => ({ period: { from: '', to: '' }, detailed: true, people: [person('2', 'Zed Person', { overdue: 2 }), person('1', 'Amy Person')] })
    wrap(<StaffListCard />)
    const bars = await screen.findAllByRole('progressbar')
    expect(bars[0]).toHaveAccessibleName('Amy Person: 4 finished, 6 open')
    expect(bars[0]).toHaveAttribute('aria-valuenow', '40')
    expect(screen.getByText('2 late')).toBeInTheDocument()
    expect(screen.getByText('AP', { selector: 'span' })).toBeInTheDocument()
  })
  it('has an empty state, a loading skeleton and an error with a retry', async () => {
    handler = () => ({ period: { from: '', to: '' }, detailed: true, people: [] })
    const { unmount } = wrap(<StaffListCard />)
    expect(screen.getByText(/Loading: How is the team doing/)).toBeInTheDocument()
    expect(await screen.findByText('Nobody has been added to your team yet.')).toBeInTheDocument()
    unmount()
    handler = () => {
      throw new Error('The server did not answer')
    }
    wrap(<StaffListCard />)
    expect(await screen.findByRole('button', { name: /retry|try again/i })).toBeInTheDocument()
  })
})

describe('friendlyAction', () => {
  it('turns a logged request into words, dropping verbs, versions and identifiers', () => {
    expect(friendlyAction('POST /api/v1/clients/4c298b50-b478-40b0-8332-854a8764fa73/invoices/upload/')).toBe('Invoices: upload')
    expect(friendlyAction('PATCH /api/v1/firm/people/12/')).toBe('Firm: people')
    expect(friendlyAction('DELETE /api/v1/clients/4c298b50-b478-40b0-8332-854a8764fa73/')).toBe('Changed something')
  })
  it('leaves a sentence the server already wrote alone', () => {
    expect(friendlyAction('Set up or used their second factor')).toBe('Set up or used their second factor')
  })
})

describe('the activity card', () => {
  it('lists the newest log entries and marks a refused one in words', async () => {
    handler = () => ({
      count: 2,
      results: [
        { id: 'r1', at: '2026-10-11T08:00:00Z', who: 'Person One', email: null, action: 'Posted an entry', client_id: null, succeeded: true, status_code: 200, ip_address: null },
        { id: 'r2', at: '2026-10-11T07:00:00Z', who: 'Person Two', email: null, action: 'Tried to seal the books', client_id: null, succeeded: false, status_code: 403, ip_address: null },
      ],
    })
    wrap(<ActivityCard />)
    expect(await screen.findByText('Posted an entry')).toBeInTheDocument()
    expect(screen.getByText('refused')).toBeInTheDocument()
  })
})

describe('person cards', () => {
  it('derives a status only from real fields: late means needs attention, nothing assigned is idle', () => {
    expect(personStatus({ overdue: 1, open_items: 2, finished_in_period: 1, assigned_clients: 1 })).toBe('attention')
    expect(personStatus({ overdue: 0, open_items: 2, finished_in_period: 1, assigned_clients: 1 })).toBe('on_track')
    expect(personStatus({ overdue: 0, open_items: 0, finished_in_period: 0, assigned_clients: 0 })).toBe('idle')
    expect(personStatus({ overdue: 3, open_items: 2, finished_in_period: 1, assigned_clients: 1 }, false)).toBe('on_track')
  })
  it('shows the five counts, the completion bar, the status chip and the measured medians when they exist', () => {
    render(<PersonCard p={person('1', 'Amy Person', { overdue: 1 }) as never} detailed days={3.2} signed={2} />)
    const card = screen.getByRole('article', { name: 'Amy Person' })
    for (const label of ['Clients', 'Finished', 'Open', 'Waiting', 'Late']) expect(within(card).getByText(label)).toBeInTheDocument()
    expect(within(card).getByText('Needs attention')).toBeInTheDocument()
    expect(within(card).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
    expect(within(card).getByText('Books signed off:')).toBeInTheDocument()
  })
  it('leaves the medians out when the server did not measure them', () => {
    render(<PersonCard p={person('1', 'Amy Person') as never} detailed />)
    expect(screen.queryByText(/upload to posted/)).not.toBeInTheDocument()
  })
  it('draws one card per person, in name order, with team totals above', async () => {
    handler = (path) =>
      path.includes('metrics')
        ? { turnaround: [{ member: { id: '1', name: 'Amy Person' }, statements_completed: 3, median_days_upload_to_posted: 2.5, books_signed_off: 1, median_days_request_to_sign_off: null }] }
        : { period: { from: '', to: '' }, detailed: true, people: [person('2', 'Zed Person'), person('1', 'Amy Person')] }
    wrap(<PersonCards range={{ from: '2026-10-01', to: '2026-10-11' }} onSelect={() => {}} />)
    const cards = await screen.findAllByRole('article')
    expect(cards.map((c) => c.getAttribute('aria-label'))).toEqual(['Amy Person', 'Zed Person'])
    expect(await within(cards[0]!).findByText('Books signed off:')).toBeInTheDocument()
    expect(screen.getByText('Team members').closest('div.rounded-xl')).toHaveTextContent('2')
  })
  it('shows a card-shaped skeleton, an empty state and an error', async () => {
    handler = () => ({ period: { from: '', to: '' }, detailed: true, people: [] })
    const { unmount } = wrap(<PersonCards range={{ from: '2026-10-01', to: '2026-10-11' }} onSelect={() => {}} />)
    expect(screen.getByText('Adding up the work…')).toBeInTheDocument()
    expect(await screen.findByText('Nobody on the team yet')).toBeInTheDocument()
    unmount()
    handler = () => {
      throw new Error('boom')
    }
    wrap(<PersonCards range={{ from: '2026-10-01', to: '2026-10-11' }} onSelect={() => {}} />)
    expect(await screen.findByRole('button', { name: /retry|try again/i })).toBeInTheDocument()
  })
})
