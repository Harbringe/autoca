import { CLIENT_NAV } from './clientNav'
import { openClientGroups, sidebarPlan } from './sidebarNav'

const all = () => true
const ids = (p: ReturnType<typeof sidebarPlan>) => p.groups.flatMap((g) => g.items.map((i) => i.id))

describe('sidebarPlan', () => {
  it('lists every module when no client is selected', () => {
    const p = sidebarPlan({ hasClient: false, can: all, hideSoon: false })
    expect(ids(p)).toContain('bookkeeping')
    expect(ids(p)).toContain('taxation')
    expect(p.more).toEqual([])
  })
  it('hides the coming-soon modules when asked', () => {
    expect(ids(sidebarPlan({ hasClient: false, can: all, hideSoon: true }))).not.toContain('audit')
  })
  it('drops what the client screens already cover once a client is selected', () => {
    const p = sidebarPlan({ hasClient: true, can: all, hideSoon: false })
    expect(ids(p)).toEqual(['dashboard', 'clients', 'pipeline', 'alerts', 'staff', 'settings'])
    expect(p.more.map((i) => i.id)).toEqual(['taxation', 'audit', 'compliance', 'ai', 'analytics'])
  })
  it('keeps the soon items out of More when hidden', () => {
    expect(sidebarPlan({ hasClient: true, can: all, hideSoon: true }).more).toEqual([])
  })
  it('respects permissions', () => {
    const p = sidebarPlan({ hasClient: true, can: () => false, hideSoon: true })
    expect(ids(p)).toEqual(['settings'])
  })
})

describe('openClientGroups', () => {
  it('opens the first group and the one with the current screen', () => {
    expect(openClientGroups(CLIENT_NAV, 'tds')).toEqual(['Get the data in', 'Compliance'])
    expect(openClientGroups(CLIENT_NAV, '')).toEqual(['Get the data in'])
    expect(openClientGroups(CLIENT_NAV, undefined)).toEqual(['Get the data in'])
  })
})
