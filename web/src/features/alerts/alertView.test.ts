import type { Alert } from '@/api/types'
import { alertKey, badgeText, clientsOf, filterAlerts, flatten, groupAlerts, severityCounts, sortAlerts } from './alertView'

const a = (severity: Alert['severity'], title: string) => ({ severity, title }) as Alert
const feed = [a('medium', 'm1'), a('critical', 'c1'), a('high', 'h1'), a('critical', 'c2'), a('medium', 'm2')]

describe('alert ordering and filtering', () => {
  it('puts the most serious first and keeps the server order within a level', () => {
    expect(sortAlerts(feed).map((x) => x.title)).toEqual(['c1', 'c2', 'h1', 'm1', 'm2'])
  })
  it('narrows by severity', () => {
    expect(filterAlerts(feed, 'critical').map((x) => x.title)).toEqual(['c1', 'c2'])
    expect(filterAlerts(feed, 'all')).toHaveLength(5)
  })
  it('counts each level', () => {
    expect(severityCounts(feed)).toEqual({ all: 5, critical: 2, high: 1, medium: 2 })
  })
  it('caps the badge at 99+', () => {
    expect(badgeText(7)).toBe('7')
    expect(badgeText(99)).toBe('99')
    expect(badgeText(100)).toBe('99+')
  })
})

describe('alerts in groups', () => {
  const full = (client: string, name: string, severity: Alert['severity'], title: string, over: Partial<Alert> = {}) =>
    ({ client, client_name: name, severity, title, kind: 'review', to: `/clients/${client}/review`, search: {}, ...over }) as Alert
  const mixed = [
    full('b', 'Patil Traders', 'medium', 'p-med'),
    full('a', 'Laxmi', 'critical', 'l-crit'),
    full('a', 'Laxmi', 'medium', 'l-med'),
    full('b', 'Patil Traders', 'high', 'p-high'),
  ]

  it('groups by severity, most serious first, leaving out a level with nothing in it', () => {
    const groups = groupAlerts(mixed, 'severity')
    expect(groups.map((g) => [g.label, g.items.map((x) => x.title)])).toEqual([
      ['Urgent', ['l-crit']],
      ['Important', ['p-high']],
      ['To do', ['p-med', 'l-med']],
    ])
  })

  it('groups by client in name order, each client most serious first', () => {
    const groups = groupAlerts(mixed, 'client')
    expect(groups.map((g) => [g.label, g.items.map((x) => x.title)])).toEqual([
      ['Laxmi', ['l-crit', 'l-med']],
      ['Patil Traders', ['p-high', 'p-med']],
    ])
    expect(groups[0]!.client).toEqual({ id: 'a', name: 'Laxmi' })
  })

  it('keeps one flat list in severity order, and none at all for nothing', () => {
    expect(groupAlerts(mixed, 'none')).toHaveLength(1)
    expect(flatten(groupAlerts(mixed, 'none')).map((x) => x.title)).toEqual(['l-crit', 'p-high', 'p-med', 'l-med'])
    expect(groupAlerts([], 'none')).toEqual([])
    expect(groupAlerts([], 'client')).toEqual([])
  })

  it('counts each client, and how many of its alerts are urgent', () => {
    expect(clientsOf(mixed)).toEqual([
      { id: 'a', name: 'Laxmi', count: 2, urgent: 1 },
      { id: 'b', name: 'Patil Traders', count: 2, urgent: 0 },
    ])
  })

  it('tells two alerts of one kind apart when they open different screens', () => {
    const needs = full('a', 'Laxmi', 'medium', 'Rows need a ledger', { search: { stage: 'unresolved' } })
    const ready = full('a', 'Laxmi', 'medium', 'Rows ready to post', { search: { stage: 'pending_approval' } })
    expect(alertKey(needs)).not.toBe(alertKey(ready))
  })
})
