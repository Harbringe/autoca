// Every screen inside one client, as the client panel lists them: one flat list in the order the work
// goes (capture, books, compliance, output), with small dividers. Pure data so it can be tested; the
// permission on each is the same one its screen already needs.

export interface ClientNavItem {
  /** The path segment after /clients/<id>; empty for the client overview. */
  screen: string
  label: string
  /** Shown to people holding any one of these. */
  permission: string | string[]
  /** Set on the first item of a block: the small divider label above it. */
  section?: string
  /** Sits at the foot of the panel, apart from the workflow. */
  bottom?: boolean
}

export const CLIENT_NAV: ClientNavItem[] = [
  { screen: '', label: 'Overview', permission: 'client.view' },
  { screen: 'statements', label: 'Statements', permission: 'transaction.view', section: 'Capture' },
  { screen: 'review', label: 'Review', permission: 'transaction.view' },
  { screen: 'documents', label: 'Documents', permission: 'document.view' },
  { screen: 'bookkeeping', label: 'Summary', permission: 'report.view', section: 'Books' },
  { screen: 'daybook', label: 'Day Book', permission: 'journal.view' },
  { screen: 'ledgers', label: 'Ledgers', permission: 'report.view' },
  { screen: 'masters', label: 'Parties & rules', permission: 'report.view' },
  { screen: 'bills', label: 'Purchases & Sales', permission: 'report.view' },
  { screen: 'invoices', label: 'Invoices', permission: 'report.view' },
  { screen: 'open-items', label: 'To fix', permission: 'report.view' },
  { screen: 'tds', label: 'TDS', permission: 'report.view', section: 'Compliance' },
  { screen: 'payroll', label: 'Payroll', permission: 'report.view' },
  { screen: 'assets', label: 'Assets', permission: 'report.view' },
  { screen: 'gst', label: 'GST', permission: 'gst.view' },
  { screen: 'reports', label: 'Reports', permission: 'report.view', section: 'Output' },
  { screen: 'books', label: 'Sign-off', permission: 'report.view' },
  { screen: 'team', label: 'Client settings', permission: ['team.view', 'client.update'], bottom: true },
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
