// One client's screen: a header that says which screen it is and where the books stand.
//
// The client panel names the places; a place's closely related screens are the tab row under the heading,
// and its alerts and "Upload bank statement" sit together at the right of the heading. "Upload bank statement" is shown
// where bank rows are the subject (the overview, the pipeline, statements, review and the books summary), not on every page: a
// purchases or GST page has its own way of adding things. `u` does it from anywhere.

import { useQuery } from '@tanstack/react-query'
import { Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { Lock, Upload } from 'lucide-react'
import { booksStatus, clientDetail } from '@/api/queries/clients'
import type { AlertModule } from '@/api/types'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { TabNav, type TabItem } from '@/components/ui/tabs'
import { lockLabel } from '@/features/books/state'
import { useAssistantLoop } from '@/features/assistant/useAssistant'
import { UploadProvider, useUpload } from '@/features/statements/UploadDialog'
import { fyLabel } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { clientScreenName, clientScreenOf, clientTabsFor } from '@/lib/clientNav'
import { moduleOf } from '@/lib/modules'
import { reviewSummary } from '@/api/queries/clients'
import { REPORT_TABS } from '@/features/reports/tabs'
import { useFy } from '@/features/shell/useFy'
import { ModuleAlerts } from '@/features/alerts/AlertList'
import { useSession } from '@/session/session'

/** The client screens where uploading a bank statement is the natural next step. */
const UPLOAD_SCREENS = new Set(['', 'pipeline', 'statements', 'review', 'bookkeeping'])

export function Workspace({ clientId }: { clientId: string }) {
  return (
    <UploadProvider clientId={clientId}>
      <WorkspaceInner clientId={clientId} />
    </UploadProvider>
  )
}

function WorkspaceInner({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const navigate = useNavigate()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const upload = useUpload()
  const client = useQuery(clientDetail(clientId))
  const books = useQuery({ ...booksStatus(clientId), enabled: can('report.view') })
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  const { fy, setFy, explicit, ready, dataYears } = useFy()
  const latestYear = dataYears[dataYears.length - 1]
  // While this client is open, the assistant reads the rows waiting for it, a few at a time.
  useAssistantLoop(clientId)

  const go = (to: string) => () => void navigate({ to: to as never, params: { clientId } as never })
  useHotkey('u', 'Upload a bank statement', () => can('document.upload') && upload.open(), 'This client')
  // Module jumps (g d, g c, g b, g s, g r, g g) belong to the shell; these are this client's own screens.
  useHotkey('g o', 'This client: Overview', go('/clients/$clientId'), 'Go to')
  useHotkey('g v', 'This client: Review', go('/clients/$clientId/review'), 'Go to')
  useHotkey('g l', 'This client: Ledgers', go('/clients/$clientId/ledgers'), 'Go to')
  useHotkey('g k', 'This client: Sign-off', go('/clients/$clientId/books'), 'Go to')
  useHotkey('g e', 'This client: Client settings', () => (can('team.view') || can('client.update')) && go('/clients/$clientId/team')(), 'Go to')
  useHotkey('g m', 'This client: Parties & rules', go('/clients/$clientId/masters'), 'Go to')

  if (client.isPending) return <Spinner label="Opening client…" />
  if (client.error) return <ErrorState error={client.error} retry={() => void client.refetch()} />

  const lock = books.data ? lockLabel(books.data) : null

  const module = moduleOf(path)
  const p = { clientId }
  // The panel names the places; the closely related screens of a place are the tab row under the heading.
  const screen = clientScreenOf(path)
  const tabs: TabItem[] =
    module === 'reports'
      ? REPORT_TABS.map((t) => ({ to: '/clients/$clientId/reports', params: p, label: t.label, search: { report: t.tab } }))
      : clientTabsFor(path, can).map((t) => ({
          to: t.screen ? `/clients/$clientId/${t.screen}` : '/clients/$clientId',
          params: p,
          label: t.label,
          exact: true,
          count: t.screen === 'review' ? summary.data?.total : undefined,
        }))
  // Alerts follow where you are: a place shows its own and those of its tabs; the client's home and pipeline show all of its.
  const alertModule = module && module !== 'clients' ? (module as AlertModule) : undefined
  const title = clientScreenName(path) ?? client.data.name
  // Uploading is the point of the Statements screen; elsewhere it is a quiet second action.
  const upload_primary = screen === 'statements'
  const showsUpload = UPLOAD_SCREENS.has(screen ?? '')
  // One purchase or sale on its own page has its own back link and its own alerts; the section tabs and the module's
  // alerts would only repeat them.
  const onItemPage = /\/bills\/[^/]+/.test(path)

  return (
    <div className="grid gap-4 [&>*]:min-w-0">
      <header className="no-print flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-sm:w-full">
          <div className="truncate text-[13px] text-muted-foreground">{client.data.name}</div>
          <h1 className="text-[26px] leading-8 xl:text-[28px] xl:leading-[34px]">{title}</h1>
          {/* The books' state and the year are in the client panel and the top bar already; only what they do not say is here. */}
          {lock && (
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm text-muted-foreground">
              <Badge tone="info" icon={<Lock aria-hidden />}>
                {lock}
              </Badge>
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {can('client.view') && module !== 'alerts' && screen !== 'team' && !onItemPage && <ModuleAlerts module={alertModule} clientId={clientId} />}
          {can('document.upload') && showsUpload && (
            <Button variant={upload_primary ? 'primary' : 'secondary'} onClick={upload.open} className="max-sm:px-3" aria-label="Upload bank statement">
              <Upload />
              <span className="max-sm:hidden">Upload bank statement</span>
              <span className="sm:hidden">Upload</span>
            </Button>
          )}
        </div>
      </header>

      {tabs.length > 0 && !onItemPage && <TabNav label={`${title} sections`} items={tabs} maxVisible={7} />}

      {explicit && latestYear !== undefined && !dataYears.includes(fy) && (
        <p className="no-print -mt-2 text-[13px] text-muted-foreground">
          No statements or vouchers in FY {fyLabel(fy)}; this client’s data is in FY {dataYears.map(fyLabel).join(', FY ')}.{' '}
          <button type="button" className="font-medium text-link underline underline-offset-2" onClick={() => setFy(latestYear)}>
            Show FY {fyLabel(latestYear)}
          </button>
        </p>
      )}

      {ready ? <Outlet /> : <Spinner label="Finding this client’s latest year…" />}
    </div>
  )
}
