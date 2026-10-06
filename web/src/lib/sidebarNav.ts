// What the sidebar lists. One menu, never two: with no client selected it is the firm's modules; with a
// client selected the client's own screens (lib/clientNav.ts) take the place of the modules that would
// only repeat them, and what is left is firm-level. Pure data and filters so it can be tested.

import type { ModuleId } from './modules'

export interface NavItem {
  id: ModuleId
  label: string
  /** Shown only to people holding this permission. */
  permission?: string
  /** No screen yet: the link goes to /soon/<id>. */
  soon?: boolean
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const FIRM_GROUPS: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { id: 'dashboard', label: 'Dashboard', permission: 'client.view' },
      { id: 'clients', label: 'Clients', permission: 'client.view' },
    ],
  },
  {
    label: 'Workflow',
    items: [
      { id: 'pipeline', label: 'Work pipeline', permission: 'client.view' },
      { id: 'documents', label: 'Documents', permission: 'document.view' },
    ],
  },
  {
    label: 'Accounting',
    items: [
      { id: 'bookkeeping', label: 'Bookkeeping', permission: 'report.view' },
      { id: 'bank', label: 'Bank statements', permission: 'transaction.view' },
      { id: 'gst', label: 'GST reconciliation', permission: 'gst.view' },
      { id: 'taxation', label: 'Taxation / ITR', soon: true },
    ],
  },
  {
    label: 'Assurance',
    items: [
      { id: 'audit', label: 'Audit', soon: true },
      { id: 'compliance', label: 'Compliance', soon: true },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { id: 'reports', label: 'Reports', permission: 'report.view' },
      { id: 'ai', label: 'AI assistant', soon: true },
      { id: 'analytics', label: 'Firm analytics', soon: true },
    ],
  },
  {
    label: 'Management',
    items: [
      { id: 'staff', label: 'Staff performance', permission: 'client.view' },
      { id: 'alerts', label: 'Alerts', permission: 'client.view' },
      { id: 'settings', label: 'Settings' },
    ],
  },
]

/** Firm modules that a selected client's own screens already cover. */
const COVERED_BY_CLIENT = new Set<ModuleId>(['documents', 'bookkeeping', 'bank', 'gst', 'reports'])

/** What stays at firm level once a client is selected. */
const FIRM_WITH_CLIENT: ModuleId[] = ['dashboard', 'clients', 'pipeline', 'alerts', 'staff', 'settings']

export interface SidebarPlan {
  groups: NavGroup[]
  /** Modules not built yet, tucked away. Empty when the person hides them or a client is not selected. */
  more: NavItem[]
}

export function sidebarPlan({ hasClient, can, hideSoon }: { hasClient: boolean; can: (permission: string) => boolean; hideSoon: boolean }): SidebarPlan {
  const allowed = (item: NavItem) => !item.permission || can(item.permission)
  if (!hasClient) {
    const groups = FIRM_GROUPS.map((g) => ({ label: g.label, items: g.items.filter((i) => allowed(i) && !(i.soon && hideSoon)) })).filter((g) => g.items.length > 0)
    return { groups, more: [] }
  }
  const all = FIRM_GROUPS.flatMap((g) => g.items)
  const firm = FIRM_WITH_CLIENT.map((id) => all.find((i) => i.id === id)!).filter(allowed)
  const more = hideSoon ? [] : all.filter((i) => i.soon && !COVERED_BY_CLIENT.has(i.id))
  return { groups: firm.length ? [{ label: 'Firm', items: firm }] : [], more }
}

/** Which client-screen groups start open: the first, and the one holding the current screen. */
export function openClientGroups(groups: { label: string; screens: { screen: string }[] }[], current: string | undefined): string[] {
  const open = new Set<string>()
  if (groups[0]) open.add(groups[0].label)
  if (current !== undefined) for (const g of groups) if (g.screens.some((s) => s.screen === current)) open.add(g.label)
  return [...open]
}
