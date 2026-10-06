import { createMemoryHistory, createRouter } from '@tanstack/react-router'
import { routeTree } from '@/routeTree.gen'
import { CLIENT_NAV, activeClientItem, clientNavFor, clientScreenOf, clientScreenPath, clientScreenTitle, stripFor, stripIsActive } from './clientNav'

const all = () => true
const only = (...held: string[]) => (p: string) => held.includes(p)

describe('the client panel list', () => {
  it('builds the address of each screen, the overview being the bare client', () => {
    expect(clientScreenPath('abc', '')).toBe('/clients/abc')
    expect(clientScreenPath('abc', 'daybook')).toBe('/clients/abc/daybook')
  })
  it('says which screen of a client the address is on', () => {
    expect(clientScreenOf('/clients/abc')).toBe('')
    expect(clientScreenOf('/clients/abc/tds')).toBe('tds')
    expect(clientScreenOf('/clients/abc/tds?fy=2025')).toBe('tds')
    expect(clientScreenOf('/dashboard')).toBeUndefined()
    expect(clientScreenOf('/clients')).toBeUndefined()
  })
  it('lists each screen once', () => {
    const screens = CLIENT_NAV.map((s) => s.screen)
    expect(new Set(screens).size).toBe(screens.length)
  })
  it('runs in the order the work goes, with the dividers of the design', () => {
    const { items, bottom } = clientNavFor(all)
    expect(items.map((i) => i.label)).toEqual([
      'Overview', 'Statements', 'Review', 'Documents', 'Summary', 'Day Book', 'Ledgers', 'Parties & rules', 'Purchases & Sales', 'Invoices', 'To fix',
      'TDS', 'Payroll', 'Assets', 'GST', 'Reports', 'Sign-off',
    ])
    expect(items.filter((i) => i.section).map((i) => i.section)).toEqual(['Capture', 'Books', 'Compliance', 'Output'])
    expect(bottom.map((i) => i.label)).toEqual(['Client settings'])
  })
  it('shows only what the person may open', () => {
    expect(clientNavFor(() => false)).toEqual({ items: [], bottom: [] })
    const reviewer = clientNavFor(only('client.view', 'transaction.view', 'document.view'))
    expect(reviewer.items.map((i) => i.label)).toEqual(['Overview', 'Statements', 'Review', 'Documents'])
    expect(reviewer.bottom).toEqual([])
    const books = clientNavFor(only('report.view', 'journal.view'))
    expect(books.items.map((i) => i.label)).toContain('Day Book')
    expect(books.items.map((i) => i.label)).not.toContain('GST')
  })
  it('gives Client settings to anyone who may see the team or edit the client', () => {
    expect(clientNavFor(only('team.view')).bottom).toHaveLength(1)
    expect(clientNavFor(only('client.update')).bottom).toHaveLength(1)
    expect(clientNavFor(only('client.view')).bottom).toHaveLength(0)
  })
  it('names a screen on its page as it is named in the panel, with two fuller names', () => {
    const title = (screen: string) => clientScreenTitle(CLIENT_NAV.find((i) => i.screen === screen)!)
    expect(title('daybook')).toBe('Day Book')
    expect(title('books')).toBe('Sign-off')
    expect(title('bookkeeping')).toBe('Books summary')
    expect(title('gst')).toBe('GST reconciliation')
  })
})

describe('every client route has exactly one active item', () => {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: ['/'] }) })
  const clientRoutes = Object.keys(router.routesByPath)
    .filter((p) => p.startsWith('/clients/$clientId'))
    .map((p) => p.replace('$clientId', 'c1').replace(/\/$/, ''))

  it('finds the client routes of the route tree', () => {
    expect(clientRoutes.length).toBeGreaterThanOrEqual(CLIENT_NAV.length)
  })
  it('lights one panel item for each, and every panel item belongs to a route', () => {
    const lit = clientRoutes.map((p) => activeClientItem(p))
    expect(lit.every((i) => i !== undefined)).toBe(true)
    // One route per item, one item per route.
    expect(new Set(lit).size).toBe(lit.length)
    expect(new Set(lit)).toEqual(new Set(CLIENT_NAV))
  })
  it('keeps the same item lit when the address carries a search or a deeper path', () => {
    expect(activeClientItem('/clients/c1/reports?report=tb')).toBe(CLIENT_NAV.find((i) => i.screen === 'reports'))
    expect(activeClientItem('/clients/c1/gst/run')).toBe(CLIENT_NAV.find((i) => i.screen === 'gst'))
    expect(activeClientItem('/clients')).toBeUndefined()
    expect(activeClientItem('/dashboard')).toBeUndefined()
  })
})

describe('the phone strip', () => {
  it('holds the five screens used most, for those who may open them', () => {
    expect(stripFor(all).map((i) => i.label)).toEqual(['Overview', 'Statements', 'Review', 'Books', 'Reports'])
    expect(stripFor(only('client.view', 'report.view')).map((i) => i.label)).toEqual(['Overview', 'Reports'])
  })
  it('counts the books screens as Books', () => {
    const books = stripFor(all).find((i) => i.label === 'Books')!
    for (const path of ['/clients/c1/daybook', '/clients/c1/ledgers', '/clients/c1/bookkeeping', '/clients/c1/open-items']) expect(stripIsActive(books, path)).toBe(true)
    expect(stripIsActive(books, '/clients/c1/review')).toBe(false)
    expect(stripIsActive(books, '/dashboard')).toBe(false)
  })
})
