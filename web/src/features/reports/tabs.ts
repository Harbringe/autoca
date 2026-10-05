export type ReportTab = 'tb' | 'pl' | 'bs' | 'payables' | 'receivables' | 'recon'

/** The reports, in the order they are read. They are the tab row of the Reports module. */
export const REPORT_TABS: { tab: ReportTab; label: string }[] = [
  { tab: 'tb', label: 'Trial Balance' },
  { tab: 'pl', label: 'Profit & Loss' },
  { tab: 'bs', label: 'Balance Sheet' },
  { tab: 'payables', label: 'Payables' },
  { tab: 'receivables', label: 'Receivables' },
  { tab: 'recon', label: 'Bank reconciliation' },
]
