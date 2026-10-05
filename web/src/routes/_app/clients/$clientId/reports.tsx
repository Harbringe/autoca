import { createFileRoute } from '@tanstack/react-router'
import { ReportsScreen, type ReportTab } from '@/features/reports/ReportsScreen'

const TABS: ReportTab[] = ['tb', 'pl', 'bs', 'payables', 'receivables', 'recon']

export const Route = createFileRoute('/_app/clients/$clientId/reports')({
  // The tab is always in the search (Trial Balance by default), so each tab link can tell it is current.
  validateSearch: (search: Record<string, unknown>): { report: ReportTab } => ({
    report: TABS.includes(search.report as ReportTab) ? (search.report as ReportTab) : 'tb',
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { report } = Route.useSearch()
  return <ReportsScreen clientId={clientId} report={report} />
}
