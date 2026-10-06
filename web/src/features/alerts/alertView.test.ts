import type { Alert } from '@/api/types'
import { badgeText, filterAlerts, severityCounts, sortAlerts } from './alertView'

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
