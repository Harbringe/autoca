// Every screen inside one client, as the sidebar lists them once a client is selected. Pure data so
// it can be tested; the permission on each is the same one its screen already needs.

export interface ClientScreen {
  /** The path segment after /clients/<id>; empty for the client overview. */
  screen: string
  label: string
  permission: string
}

export interface ClientScreenGroup {
  label: string
  screens: ClientScreen[]
}

export const CLIENT_NAV: ClientScreenGroup[] = [
  {
    label: 'Get the data in',
    screens: [
      { screen: '', label: 'Overview', permission: 'client.view' },
      { screen: 'documents', label: 'Documents', permission: 'document.view' },
      { screen: 'statements', label: 'Statements', permission: 'transaction.view' },
      { screen: 'review', label: 'Review', permission: 'transaction.view' },
      { screen: 'invoices', label: 'Invoices', permission: 'report.view' },
    ],
  },
  {
    label: 'The books',
    screens: [
      { screen: 'daybook', label: 'Day Book', permission: 'journal.view' },
      { screen: 'bills', label: 'Purchases & Sales', permission: 'report.view' },
      { screen: 'open-items', label: 'To fix', permission: 'report.view' },
      { screen: 'ledgers', label: 'Ledgers', permission: 'report.view' },
      { screen: 'masters', label: 'Parties & rules', permission: 'report.view' },
    ],
  },
  {
    label: 'Compliance',
    screens: [
      { screen: 'tds', label: 'TDS', permission: 'report.view' },
      { screen: 'payroll', label: 'Payroll', permission: 'report.view' },
      { screen: 'assets', label: 'Assets', permission: 'report.view' },
      { screen: 'gst', label: 'GST', permission: 'gst.view' },
    ],
  },
  {
    label: 'Results',
    screens: [
      { screen: 'reports', label: 'Reports', permission: 'report.view' },
      { screen: 'books', label: 'Books & sign-off', permission: 'report.view' },
    ],
  },
]

/** Where a screen is for this client. */
export const clientScreenPath = (clientId: string, screen: string): string => (screen ? `/clients/${clientId}/${screen}` : `/clients/${clientId}`)

/** Which screen of the client the address is on ('' for the overview), or undefined outside a client. */
export function clientScreenOf(pathname: string): string | undefined {
  const parts = pathname.split('?')[0]!.split('/').filter(Boolean)
  return parts[0] === 'clients' && parts[1] ? (parts[2] ?? '') : undefined
}
