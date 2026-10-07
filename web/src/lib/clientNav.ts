// Every screen inside one client, as the client panel lists them: one flat list in the order the work
// goes (capture, books, compliance, output), with small dividers. Pure data so it can be tested; the
// permission on each is the same one its screen already needs.

import {
  ArrowLeftRight,
  BarChart3,
  BookMarked,
  BookOpen,
  BookUser,
  Boxes,
  FileSpreadsheet,
  FolderOpen,
  LayoutGrid,
  Landmark,
  ListChecks,
  NotebookText,
  Percent,
  Receipt,
  Settings2,
  ShieldCheck,
  Wallet,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

export interface ClientNavItem {
  /** The path segment after /clients/<id>; empty for the client overview. */
  screen: string
  label: string
  /** The line icon beside the label, in the panel and in the phone drawer. */
  icon: LucideIcon
  /** Shown to people holding any one of these. */
  permission: string | string[]
  /** Set on the first item of a block: the small divider label above it. */
  section?: string
  /** Sits at the foot of the panel, apart from the workflow. */
  bottom?: boolean
}

export const CLIENT_NAV: ClientNavItem[] = [
  { screen: '', label: 'Overview', icon: LayoutGrid, permission: 'client.view' },
  { screen: 'statements', label: 'Statements', icon: Landmark, permission: 'transaction.view', section: 'Capture' },
  { screen: 'review', label: 'Review', icon: ListChecks, permission: 'transaction.view' },
  { screen: 'documents', label: 'Documents', icon: FolderOpen, permission: 'document.view' },
  { screen: 'bookkeeping', label: 'Summary', icon: BookOpen, permission: 'report.view', section: 'Books' },
  { screen: 'daybook', label: 'Day Book', icon: NotebookText, permission: 'journal.view' },
  { screen: 'ledgers', label: 'Ledgers', icon: BookMarked, permission: 'report.view' },
  { screen: 'masters', label: 'Parties & rules', icon: BookUser, permission: 'report.view' },
  { screen: 'bills', label: 'Purchases & Sales', icon: ArrowLeftRight, permission: 'report.view' },
  { screen: 'invoices', label: 'Invoices', icon: Receipt, permission: 'report.view' },
  { screen: 'open-items', label: 'To fix', icon: Wrench, permission: 'report.view' },
  { screen: 'tds', label: 'TDS', icon: Percent, permission: 'report.view', section: 'Compliance' },
  { screen: 'payroll', label: 'Payroll', icon: Wallet, permission: 'report.view' },
  { screen: 'assets', label: 'Assets', icon: Boxes, permission: 'report.view' },
  { screen: 'gst', label: 'GST', icon: FileSpreadsheet, permission: 'gst.view' },
  { screen: 'reports', label: 'Reports', icon: BarChart3, permission: 'report.view', section: 'Output' },
  { screen: 'books', label: 'Sign-off', icon: ShieldCheck, permission: 'report.view' },
  { screen: 'team', label: 'Client settings', icon: Settings2, permission: ['team.view', 'client.update'], bottom: true },
]

const allowed = (item: ClientNavItem, can: (permission: string) => boolean) =>
  (Array.isArray(item.permission) ? item.permission : [item.permission]).some((p) => can(p))

/** What this person sees in the panel: the workflow items in order, and the foot item. */
export function clientNavFor(can: (permission: string) => boolean): { items: ClientNavItem[]; bottom: ClientNavItem[] } {
  const visible = CLIENT_NAV.filter((i) => allowed(i, can))
  return { items: visible.filter((i) => !i.bottom), bottom: visible.filter((i) => i.bottom) }
}

/** The screen's name on its page and in the browser tab: the panel's label, except where a fuller name reads better. */
const TITLE_OVERRIDE: Record<string, string> = { bookkeeping: 'Books summary', gst: 'GST reconciliation' }
export const clientScreenTitle = (item: ClientNavItem): string => TITLE_OVERRIDE[item.screen] ?? item.label

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
  return screen === undefined ? undefined : CLIENT_NAV.find((i) => i.screen === screen)
}

/** The five screens used most, kept one thumb away on a phone. `also` are the screens that count as inside the item. */
export interface StripItem {
  screen: string
  label: string
  permission: string
  also?: string[]
}

export const PHONE_STRIP: StripItem[] = [
  { screen: '', label: 'Overview', permission: 'client.view' },
  { screen: 'statements', label: 'Statements', permission: 'transaction.view' },
  { screen: 'review', label: 'Review', permission: 'transaction.view' },
  { screen: 'daybook', label: 'Books', permission: 'journal.view', also: ['bookkeeping', 'ledgers', 'masters', 'bills', 'invoices', 'open-items'] },
  { screen: 'reports', label: 'Reports', permission: 'report.view' },
]

export const stripFor = (can: (permission: string) => boolean): StripItem[] => PHONE_STRIP.filter((i) => can(i.permission))

export const stripIsActive = (item: StripItem, pathname: string): boolean => {
  const screen = clientScreenOf(pathname)
  return screen !== undefined && (screen === item.screen || !!item.also?.includes(screen))
}
