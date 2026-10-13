import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Alert } from '@/api/types'
import { HotkeyProvider } from '@/lib/hotkeys'
import { AlertsInbox, type InboxFilter } from './AlertsInbox'

const alert = (n: number, client: string, clientName: string, severity: Alert['severity'], title: string, over: Partial<Alert> = {}): Alert =>
  ({
    kind: 'review',
    severity,
    module: 'bank',
    client,
    client_name: clientName,
    title,
    detail: `${title}: detail ${n}.`,
    to: `/clients/${client}/review`,
    search: { n: String(n) },
    amount_paise: null,
    amount_display: null,
    count: 1,
    ...over,
  }) as Alert

const MANY: Alert[] = [
  alert(1, 'laxmi', 'Laxmi', 'critical', 'TDS is overdue', { kind: 'tds', module: 'bookkeeping', to: '/clients/laxmi/tds', amount_display: '₹1,18,400.00' }),
  alert(2, 'laxmi', 'Laxmi', 'medium', 'Rows need a ledger', { count: 6 }),
  alert(3, 'patil', 'Patil Traders', 'high', 'A bank account does not agree with its statement', { kind: 'bank' }),
  alert(4, 'patil', 'Patil Traders', 'medium', 'A statement month is missing', { kind: 'statements' }),
  alert(5, 'shinde', 'Shinde Pharma', 'medium', 'Rows ready to post'),
]

function renderInbox(alerts: Alert[], { filter = {} as InboxFilter, onFilter = vi.fn() } = {}) {
  const root = createRootRoute()
  const page = createRoute({ getParentRoute: () => root, path: '/alerts', component: () => <AlertsInbox alerts={alerts} filter={filter} onFilter={onFilter} /> })
  const other = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/$screen', component: () => <p>the screen</p> })
  const router = createRouter({ routeTree: root.addChildren([page, other]), history: createMemoryHistory({ initialEntries: ['/alerts'] }) })
  render(
    <HotkeyProvider>
      <RouterProvider router={router} />
    </HotkeyProvider>,
  )
  return { router, onFilter }
}

const options = () => screen.getAllByRole('option').map((o) => o.textContent ?? '')
const detail = () => screen.getByRole('complementary', { name: 'Alert detail' })

describe('the alerts inbox', () => {
  it('lists the alerts under their severity, most serious first, and shows the first one in detail', async () => {
    renderInbox(MANY)
    await screen.findByRole('listbox', { name: 'Alerts' })
    expect(screen.getByRole('group', { name: 'Urgent' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Important' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'To do' })).toBeInTheDocument()
    expect(options()[0]).toContain('TDS is overdue')
    expect(within(detail()).getByRole('heading', { name: 'TDS is overdue' })).toBeInTheDocument()
    // what to do, the screen it opens, and the amount
    expect(within(detail()).getByText(/Deposit the challan/)).toBeInTheDocument()
    expect(within(detail()).getByRole('link', { name: /Open TDS/ })).toBeInTheDocument()
    expect(within(detail()).getByText('₹1,18,400.00')).toBeInTheDocument()
    // whose it is is on the row, since several clients share the list
    expect(options()[0]).toContain('Laxmi')
  })

  it('shows another alert in the detail pane when it is chosen, and what else is open for that client', async () => {
    renderInbox(MANY)
    fireEvent.click((await screen.findAllByRole('option'))[1]!) // the second by severity: Patil's bank account
    expect(within(detail()).getByRole('heading', { name: 'A bank account does not agree with its statement' })).toBeInTheDocument()
    const also = within(detail()).getByRole('region', { name: 'Also open for Patil Traders' })
    expect(within(also).getByText('A statement month is missing')).toBeInTheDocument()
    // and choosing one of those moves the detail to it
    fireEvent.click(within(also).getByRole('button', { name: /A statement month is missing/ }))
    expect(within(detail()).getByRole('heading', { name: 'A statement month is missing' })).toBeInTheDocument()
  })

  it('moves with J and K, wrapping nowhere, and with the arrow keys once the list has focus', async () => {
    renderInbox(MANY)
    await screen.findAllByRole('option')
    const selectedTitle = () => within(detail()).getByRole('heading', { level: 2 }).textContent
    expect(selectedTitle()).toBe('TDS is overdue')
    act(() => void fireEvent.keyDown(document.body, { key: 'j' }))
    await waitFor(() => expect(selectedTitle()).toBe('A bank account does not agree with its statement'))
    act(() => void fireEvent.keyDown(document.body, { key: 'k' }))
    await waitFor(() => expect(selectedTitle()).toBe('TDS is overdue'))
    act(() => void fireEvent.keyDown(document.body, { key: 'k' }))
    expect(selectedTitle()).toBe('TDS is overdue')
    const user = userEvent.setup()
    screen.getAllByRole('option')[0]!.focus()
    await user.keyboard('{ArrowDown}{ArrowDown}')
    await waitFor(() => expect(selectedTitle()).toBe('Rows need a ledger'))
  })

  it('opens the screen of the alert selected, with the O key', async () => {
    const { router } = renderInbox(MANY)
    await screen.findAllByRole('option')
    act(() => void fireEvent.keyDown(document.body, { key: 'o' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/clients/laxmi/tds'))
  })

  it('narrows by severity, with the count on each chip', async () => {
    renderInbox(MANY)
    await screen.findAllByRole('option')
    expect(screen.getByRole('button', { name: 'All 5' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Important 1' }))
    await waitFor(() => expect(options()).toHaveLength(1))
    expect(options()[0]).toContain('A bank account does not agree')
  })

  it('groups by client or leaves the list flat, as asked', async () => {
    renderInbox(MANY)
    await screen.findAllByRole('option')
    fireEvent.click(screen.getByRole('button', { name: 'By client' }))
    await waitFor(() => expect(screen.getByRole('group', { name: 'Laxmi' })).toBeInTheDocument())
    expect(screen.getByRole('group', { name: 'Patil Traders' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Shinde Pharma' })).toBeInTheDocument()
    // under a client's own heading its rows do not repeat its name
    expect(within(screen.getByRole('group', { name: 'Laxmi' })).getAllByRole('option')[0]!.textContent).not.toContain('Laxmi')
    fireEvent.click(screen.getByRole('button', { name: 'Flat' }))
    await waitFor(() => expect(screen.getByRole('group', { name: 'All alerts' })).toBeInTheDocument())
  })

  it('chooses a client from a searchable menu with each client’s count', async () => {
    const user = userEvent.setup()
    const { onFilter } = renderInbox(MANY)
    await screen.findAllByRole('option')
    await user.click(screen.getByRole('button', { name: /Client:/ }))
    const list = await screen.findByRole('listbox', { name: 'Clients' })
    expect(within(list).getAllByRole('option').map((o) => o.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining('All clients'), expect.stringContaining('Laxmi'), expect.stringContaining('Patil Traders'), expect.stringContaining('Shinde Pharma')]),
    )
    // Laxmi has an urgent alert, so its count is flagged
    expect(within(list).getByText('urgent').closest('li')).toHaveTextContent('Laxmi')
    await user.type(screen.getByRole('combobox', { name: 'Find a client' }), 'pat')
    expect(within(screen.getByRole('listbox', { name: 'Clients' })).getAllByRole('option')).toHaveLength(1)
    await user.keyboard('{Enter}')
    expect(onFilter).toHaveBeenCalledWith({ client: 'patil' })
  })

  it('shows only the client the address names, and says so in the menu', async () => {
    renderInbox(MANY, { filter: { client: 'patil' } })
    await screen.findAllByRole('option')
    expect(options()).toHaveLength(2)
    expect(screen.getByRole('button', { name: /Client:/ })).toHaveTextContent('Patil Traders')
  })

  it('with one client leaves the client off the rows and offers no client menu or grouping', async () => {
    renderInbox(MANY.filter((a) => a.client === 'laxmi'))
    await screen.findAllByRole('option')
    expect(screen.queryByRole('button', { name: /Client:/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'By client' })).toBeNull()
    expect(options()[0]).not.toContain('Laxmi')
    expect(screen.queryByRole('region', { name: /Also open for/ })).toBeNull()
  })

  it('says all is clear when nothing is open, and offers to clear filters when they hide everything', async () => {
    const { onFilter } = renderInbox([])
    expect(await screen.findByText('All clear')).toBeInTheDocument()
    expect(onFilter).not.toHaveBeenCalled()
  })

  it('pages a long list, 10 at a time', async () => {
    const many = Array.from({ length: 120 }, (_, i) => alert(i + 100, i % 2 ? 'a' : 'b', i % 2 ? 'Alpha' : 'Beta', 'medium', `Alert number ${i + 100}`))
    renderInbox(many)
    await screen.findByText('Showing 1–10 of 120')
    expect(options()).toHaveLength(10)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('Showing 11–20 of 120')
  })

  it('selects one alert only, even when two checks of a client open the same screen', async () => {
    const same = [
      alert(1, 'a', 'Alpha', 'high', 'Every bank row is placed and posted', { kind: 'control', to: '/clients/a/signoff', search: undefined }),
      alert(2, 'a', 'Alpha', 'high', 'Entries the assistant posted are checked by a person', { kind: 'control', to: '/clients/a/signoff', search: undefined }),
    ]
    renderInbox(same)
    await screen.findAllByRole('option')
    expect(screen.getAllByRole('option', { selected: true })).toHaveLength(1)
    fireEvent.click(screen.getAllByRole('option')[1]!)
    expect(screen.getAllByRole('option', { selected: true })).toHaveLength(1)
    expect(within(detail()).getByRole('heading', { level: 2 })).toHaveTextContent('Entries the assistant posted')
  })
})
