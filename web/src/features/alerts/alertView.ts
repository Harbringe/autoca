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

/** One alert, told apart from the rest: the same kind can stand for two screens (rows with no ledger, rows ready to post) and several checks share one screen, so the title is part of it. */
export const alertKey = (a: Alert): string => `${a.client}|${a.kind}|${a.to}|${JSON.stringify(a.search ?? {})}|${a.title}`

export type GroupBy = 'severity' | 'client' | 'none'

export interface AlertGroup {
  key: string
  /** The words on the group's header. */
  label: string
  severity?: Alert['severity']
  client?: { id: string; name: string }
  items: Alert[]
}

const SEVERITY_NAME: Record<Alert['severity'], string> = { critical: 'Urgent', high: 'Important', medium: 'To do' }

/** The clients that have alerts here, by name. */
export function clientsOf(alerts: Alert[]): { id: string; name: string; count: number; urgent: number }[] {
  const by = new Map<string, { id: string; name: string; count: number; urgent: number }>()
  for (const a of alerts) {
    const row = by.get(a.client) ?? { id: a.client, name: a.client_name, count: 0, urgent: 0 }
    row.count += 1
    if (a.severity === 'critical') row.urgent += 1
    by.set(a.client, row)
  }
  return [...by.values()].sort((a, b) => a.name.localeCompare(b.name))
}

/** The alerts in the groups the person asked for, each group in its own order: by severity, by client, or one flat list. */
export function groupAlerts(alerts: Alert[], by: GroupBy): AlertGroup[] {
  const sorted = sortAlerts(alerts)
  if (by === 'none') return sorted.length ? [{ key: 'all', label: 'All alerts', items: sorted }] : []
  if (by === 'severity') {
    return (['critical', 'high', 'medium'] as const)
      .map((severity) => ({ key: severity, label: SEVERITY_NAME[severity], severity, items: sorted.filter((a) => a.severity === severity) }))
      .filter((g) => g.items.length > 0)
  }
  return clientsOf(sorted).map((c) => ({ key: c.id, label: c.name, client: { id: c.id, name: c.name }, items: sorted.filter((a) => a.client === c.id) }))
}

/** The alerts as one list in the order the groups show them, so "next" and "previous" follow what is on screen. */
export const flatten = (groups: AlertGroup[]): Alert[] => groups.flatMap((g) => g.items)
