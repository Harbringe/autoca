// Every place inside one client, as the client panel lists them, and the tabs of each place. Pure data
// so it can be tested; the permission on each is the same one its screen already needs.

import {
  BarChart3,
  Columns3,
  BookOpen,
  FileSpreadsheet,
  FolderOpen,
  LayoutGrid,
  Landmark,
  Settings2,
  type LucideIcon,
} from 'lucide-react'

export interface ClientNavItem {
  /** The path segment after /clients/<id> where the item opens; empty for the client overview. */
  screen: string
  label: string
  /** The line icon beside the label, in the panel and in the phone drawer. */
  icon: LucideIcon
  /** Shown to people holding any one of these. */
  permission: string | string[]
  /** Other screens that count as inside this item (they are its tabs). */
  also?: string[]
  /** Sits at the foot of the panel, apart from the workflow. */
  bottom?: boolean
}

/** The panel lists the places; the closely related screens of each are tabs on the page itself. */
export const CLIENT_NAV: ClientNavItem[] = [
  { screen: '', label: 'Overview', icon: LayoutGrid, permission: 'client.view' },
  { screen: 'pipeline', label: 'Pipeline', icon: Columns3, permission: 'client.view' },
  { screen: 'statements', label: 'Bank statements', icon: Landmark, permission: 'transaction.view', also: ['review'] },
  { screen: 'documents', label: 'Documents', icon: FolderOpen, permission: 'document.view' },
  {
    screen: 'bookkeeping',
    label: 'Bookkeeping',
    icon: BookOpen,
    permission: 'report.view',
    also: ['bills', 'invoices', 'tds', 'payroll', 'assets', 'daybook', 'open-items', 'ledgers', 'masters', 'books'],
  },
  { screen: 'gst', label: 'GST', icon: FileSpreadsheet, permission: 'gst.view' },
  { screen: 'reports', label: 'Reports', icon: BarChart3, permission: 'report.view' },
  { screen: 'team', label: 'Client settings', icon: Settings2, permission: ['team.view', 'client.update'], bottom: true },
]

/** One tab of a place: the closely related screens, in the order they are used. */
export interface ClientTab {
  screen: string
  label: string
  permission: string
}

/** Tabs by the screen the place opens at. A place with no entry (Overview, Documents, ...) has no tab row. */
export const CLIENT_TABS: Record<string, ClientTab[]> = {
  statements: [
    { screen: 'statements', label: 'Statements', permission: 'transaction.view' },
    { screen: 'review', label: 'Review', permission: 'transaction.view' },
  ],
  bookkeeping: [
    { screen: 'bookkeeping', label: 'Books summary', permission: 'report.view' },
    { screen: 'bills', label: 'Purchases & Sales', permission: 'report.view' },
    { screen: 'invoices', label: 'Invoices', permission: 'report.view' },
    { screen: 'tds', label: 'TDS', permission: 'report.view' },
    { screen: 'payroll', label: 'Payroll', permission: 'report.view' },
    { screen: 'assets', label: 'Assets', permission: 'report.view' },
    { screen: 'daybook', label: 'Day Book', permission: 'journal.view' },
    { screen: 'open-items', label: 'To fix', permission: 'report.view' },
    { screen: 'ledgers', label: 'Ledgers', permission: 'report.view' },
    { screen: 'masters', label: 'Parties & rules', permission: 'report.view' },
    { screen: 'books', label: 'Sign-off', permission: 'report.view' },
  ],
}

const allowed = (item: ClientNavItem, can: (permission: string) => boolean) =>
  (Array.isArray(item.permission) ? item.permission : [item.permission]).some((p) => can(p))

/** What this person sees in the panel: the places in order, and the foot item. */
export function clientNavFor(can: (permission: string) => boolean): { items: ClientNavItem[]; bottom: ClientNavItem[] } {
  const visible = CLIENT_NAV.filter((i) => allowed(i, can))
  return { items: visible.filter((i) => !i.bottom), bottom: visible.filter((i) => i.bottom) }
}

/** The tabs this person sees for the place the address is on (empty where the place has none). */
export function clientTabsFor(pathname: string, can: (permission: string) => boolean): ClientTab[] {
  const item = activeClientItem(pathname)
  return (item && CLIENT_TABS[item.screen])?.filter((t) => can(t.permission)) ?? []
}

/** The screen's name on its page and in the browser tab: its tab's name where it has one, else the panel's. */
export function clientScreenName(pathname: string): string | undefined {
  const screen = clientScreenOf(pathname)
  const item = activeClientItem(pathname)
  if (screen === undefined || !item) return undefined
  return CLIENT_TABS[item.screen]?.find((t) => t.screen === screen)?.label ?? (item.screen === 'gst' ? 'GST reconciliation' : item.label)
}
export const clientScreenTitle = (item: ClientNavItem): string => (item.screen === 'gst' ? 'GST reconciliation' : item.label)

/** Where a screen is for this client. */
export const clientScreenPath = (clientId: string, screen: string): string => (screen ? `/clients/${clientId}/${screen}` : `/clients/${clientId}`)

/** Which screen of the client the address is on ('' for the overview), or undefined outside a client. */
export function clientScreenOf(pathname: string): string | undefined {
  const parts = pathname.split('?')[0]!.split('/').filter(Boolean)
  return parts[0] === 'clients' && parts[1] ? (parts[2] ?? '') : undefined
}

/** The one panel item the address belongs to, whatever follows the screen's own segment; undefined outside a client. */
export function activeClientItem(pathname: string): ClientNavItem | undefined {
  const screen = clientScreenOf(pathname)
  return screen === undefined ? undefined : CLIENT_NAV.find((i) => i.screen === screen || !!i.also?.includes(screen))
}

/** The places used most, kept one thumb away on a phone. `also` are the screens that count as inside the item. */
export interface StripItem {
  screen: string
  label: string
  permission: string
  also?: string[]
}

export const PHONE_STRIP: StripItem[] = [
  { screen: '', label: 'Overview', permission: 'client.view' },
  { screen: 'statements', label: 'Bank', permission: 'transaction.view', also: ['review'] },
  { screen: 'documents', label: 'Documents', permission: 'document.view' },
  { screen: 'bookkeeping', label: 'Books', permission: 'report.view', also: CLIENT_NAV.find((i) => i.screen === 'bookkeeping')!.also },
  { screen: 'gst', label: 'GST', permission: 'gst.view' },
  { screen: 'reports', label: 'Reports', permission: 'report.view' },
]

export const stripFor = (can: (permission: string) => boolean): StripItem[] => PHONE_STRIP.filter((i) => can(i.permission))

export const stripIsActive = (item: StripItem, pathname: string): boolean => {
  const screen = clientScreenOf(pathname)
  return screen !== undefined && (screen === item.screen || !!item.also?.includes(screen))
}
