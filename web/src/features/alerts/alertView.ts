// How a list of alerts is ordered and narrowed. Pure, so the bell, the page and the in-page banner agree.

import type { Alert } from '@/api/types'

export type SeverityFilter = 'all' | Alert['severity']

export const SEVERITY_RANK: Record<Alert['severity'], number> = { critical: 0, high: 1, medium: 2 }

/** Most serious first; the order the server gave breaks ties, so it stays stable. */
export function sortAlerts(alerts: Alert[]): Alert[] {
  return alerts
    .map((alert, i) => ({ alert, i }))
    .sort((a, b) => SEVERITY_RANK[a.alert.severity] - SEVERITY_RANK[b.alert.severity] || a.i - b.i)
    .map((x) => x.alert)
}

export function filterAlerts(alerts: Alert[], filter: SeverityFilter): Alert[] {
  return sortAlerts(filter === 'all' ? alerts : alerts.filter((a) => a.severity === filter))
}

export function severityCounts(alerts: Alert[]): Record<SeverityFilter, number> {
  const counts: Record<SeverityFilter, number> = { all: alerts.length, critical: 0, high: 0, medium: 0 }
  for (const a of alerts) counts[a.severity] += 1
  return counts
}

/** The bell's badge: the number, capped at 99+. */
export const badgeText = (count: number): string => (count > 99 ? '99+' : String(count))
