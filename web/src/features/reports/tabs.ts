export type ReportTab = 'tb' | 'pl' | 'bs' | 'nce' | 'payables' | 'receivables' | 'inventory' | 'gst' | 'groups' | 'budget' | 'centres' | 'recon'

/** The reports, in the order they are read. They are the tab row of the Reports module. */
export const REPORT_TABS: { tab: ReportTab; label: string }[] = [
  { tab: 'tb', label: 'Trial Balance' },
  { tab: 'pl', label: 'Profit & Loss' },
  { tab: 'bs', label: 'Balance Sheet' },
  { tab: 'nce', label: 'Financial statements (ICAI)' },
  { tab: 'groups', label: 'Group summary' },
  { tab: 'budget', label: 'Budget' },
  { tab: 'centres', label: 'Cost centres' },
  { tab: 'payables', label: 'Payables' },
  { tab: 'receivables', label: 'Receivables' },
  { tab: 'inventory', label: 'Inventory' },
  { tab: 'gst', label: 'GST tie-out' },
  { tab: 'recon', label: 'Bank reconciliation' },
]
