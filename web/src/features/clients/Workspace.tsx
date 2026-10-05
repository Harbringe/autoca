// One client's books inside a module: a header that says where they stand, and the module's tabs.
//
// The module comes from the address (Bank statements, Bookkeeping, Reports, or the client's own
// profile). Its tab row is only its own screens; the sidebar moves between modules. "Upload bank
// statement" is on every client page because it is where everything starts, and `u` does it too.

import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { ChevronLeft, ChevronRight, Lock, Upload } from 'lucide-react'
import { booksStatus, clientDetail, reviewSummary } from '@/api/queries/clients'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { TabNav, type TabItem } from '@/components/ui/tabs'
import { BOOKS_STATE_HINT, BOOKS_STATE_LABEL, BOOKS_STATE_TONE, booksState, lockLabel } from '@/features/books/state'
import { useAssistantLoop } from '@/features/assistant/useAssistant'
import { UploadProvider, useUpload } from '@/features/statements/UploadDialog'
import { fyLabel } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { moduleOf, type ModuleId } from '@/lib/modules'
import { REPORT_TABS } from '@/features/reports/tabs'
import { useFy } from '@/features/shell/useFy'
import { useSession } from '@/session/session'

const MODULE_TITLE: Partial<Record<ModuleId, string>> = {
  documents: 'Documents',
  bank: 'Bank statements',
  bookkeeping: 'Bookkeeping',
  reports: 'Reports',
  gst: 'GST reconciliation',
}

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
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  const books = useQuery({ ...booksStatus(clientId), enabled: can('report.view') })
  const { fy, setFy, explicit, ready, dataYears } = useFy()
  const latestYear = dataYears[dataYears.length - 1]
  // While this client is open, the assistant reads the rows waiting for it, a few at a time.
  useAssistantLoop(clientId)

  const go = (to: string) => () => void navigate({ to: to as never, params: { clientId } as never })
  useHotkey('u', 'Upload a bank statement', () => can('document.upload') && upload.open(), 'This client')
  // Module jumps (g d, g c, g b, g s, g r, g g) belong to the shell; these are this client's own screens.
  useHotkey('g o', 'This client: Profile', go('/clients/$clientId'), 'Go to')
  useHotkey('g v', 'This client: Review', go('/clients/$clientId/review'), 'Go to')
  useHotkey('g l', 'This client: Ledgers', go('/clients/$clientId/ledgers'), 'Go to')
  useHotkey('g k', 'This client: Books & sign-off', go('/clients/$clientId/books'), 'Go to')
  useHotkey('g e', 'This client: Settings and team', () => (can('team.view') || can('client.update')) && go('/clients/$clientId/team')(), 'Go to')
  useHotkey('g m', 'This client: Parties & rules', go('/clients/$clientId/masters'), 'Go to')

  if (client.isPending) return <Spinner label="Opening client…" />
  if (client.error) return <ErrorState error={client.error} retry={() => void client.refetch()} />

  const state = books.data ? booksState(books.data) : null
  const lock = books.data ? lockLabel(books.data) : null

  const module = moduleOf(path)
  const p = { clientId }
  const canTeam = can('team.view') || can('client.update')
  const tabs: TabItem[] =
    module === 'bank'
      ? [
          { to: '/clients/$clientId/statements', params: p, label: 'Statements' },
          { to: '/clients/$clientId/review', params: p, label: 'Review', count: summary.data?.total },
        ]
      : module === 'bookkeeping'
        ? [
              { to: '/clients/$clientId/bookkeeping', params: p, label: 'Books overview' },
              { to: '/clients/$clientId/bills', params: p, label: 'Purchases & Sales' },
              { to: '/clients/$clientId/daybook', params: p, label: 'Day Book' },
            { to: '/clients/$clientId/ledgers', params: p, label: 'Ledgers' },
            { to: '/clients/$clientId/masters', params: p, label: 'Parties & rules' },
            { to: '/clients/$clientId/books', params: p, label: 'Books & sign-off' },
          ]
        : module === 'reports'
          ? REPORT_TABS.map((t) => ({ to: '/clients/$clientId/reports', params: p, label: t.label, search: { report: t.tab } }))
          : module === 'documents'
            ? [{ to: '/clients/$clientId/documents', params: p, label: 'Files', exact: true }]
          : module === 'clients'
          ? [
          { to: '/clients/$clientId', params: p, label: 'Client profile', exact: true },
          ...(can('document.view') ? [{ to: '/clients/$clientId/documents', params: p, label: 'Documents' }] : []),
              ...(canTeam ? [{ to: '/clients/$clientId/team', params: p, label: 'Settings & team' }] : []),
            ]
          : []
  const title = module && module !== 'clients' ? MODULE_TITLE[module] : client.data.name
  // On the profile the next step's own button is the primary one; on Bank statements uploading is the point.
  const upload_primary = module === 'bank'

  return (
    <div className="grid gap-4">
      <header className="no-print flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[26px] leading-8 xl:text-[28px] xl:leading-[34px]">{title}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm text-muted-foreground">
            {module === 'clients' ? (
              <span>{client.data.lead ? `Senior CA: ${client.data.lead.name}` : 'No senior CA assigned'}</span>
            ) : (
              <span className="font-medium text-foreground">{client.data.name}</span>
            )}
            {state && (
              <Badge tone={BOOKS_STATE_TONE[state]} title={BOOKS_STATE_HINT[state]}>
                {BOOKS_STATE_LABEL[state]}
              </Badge>
            )}
            {lock && (
              <Badge tone="info" icon={<Lock aria-hidden />}>
                {lock}
              </Badge>
            )}
            <span className="num">FY {fyLabel(fy)}</span>
          </div>
        </div>
        {can('document.upload') && module !== 'gst' && (
          <Button variant={upload_primary ? 'primary' : 'secondary'} onClick={upload.open} className="max-sm:w-full">
            <Upload /> Upload bank statement
          </Button>
        )}
      </header>

      <WorkspaceBreadcrumbs
        clientId={clientId}
        clientName={client.data.name}
        module={module}
        moduleTitle={title ?? client.data.name}
        tabs={tabs}
        path={path}
      />

      {tabs.length > 0 && (
        <TabNav
          label={`${title} sections`}
          items={tabs}
          trailing={<AdjacentPages tabs={tabs} module={module} path={path} />}
        />
      )}

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

function WorkspaceBreadcrumbs({
  clientId,
  clientName,
  module,
  moduleTitle,
  tabs,
  path,
}: {
  clientId: string
  clientName: string
  module: ModuleId | undefined
  moduleTitle: string
  tabs: TabItem[]
  path: string
}) {
  const search = useRouterState({ select: (state) => state.location.search })
  const current = currentPage(tabs, module, path, search)
  const moduleRoot = tabs[0]
  const isProfile = module === 'clients'
  const currentLabel = isProfile
    ? path.endsWith('/team') ? 'Settings & team' : 'Client profile'
    : current?.label ?? moduleTitle

  return (
    <nav aria-label="Breadcrumb" className="no-print -mb-2 min-w-0 overflow-x-auto">
      <ol className="flex min-w-max items-center gap-2 text-xs text-muted-foreground">
        <li><Link to="/clients" className="hover:text-foreground hover:underline">All clients</Link></li>
        <li aria-hidden="true">/</li>
        <li><Link to="/clients/$clientId" params={{ clientId }} className="max-w-40 truncate hover:text-foreground hover:underline" title={clientName}>{clientName}</Link></li>
        <li aria-hidden="true">/</li>
        {isProfile ? (
          <li aria-current="page" className="font-medium text-heading">{currentLabel}</li>
        ) : (
          <>
            {moduleRoot && <li><Link to={moduleRoot.to as never} params={moduleRoot.params as never} className="hover:text-foreground hover:underline">{moduleTitle}</Link></li>}
            {current && <><li aria-hidden="true">/</li><li aria-current="page" className="font-medium text-heading">{currentLabel}</li></>}
          </>
        )}
      </ol>
    </nav>
  )
}

function currentPage(
  tabs: TabItem[],
  module: ModuleId | undefined,
  path: string,
  search: Record<string, unknown>,
) {
  if (module === 'reports') return tabs.find((tab) => tab.search?.report === search.report)
  const currentSegment = path.split('/').filter(Boolean).at(-1)
  return tabs.find((tab) => tab.to.split('/').filter(Boolean).at(-1) === currentSegment)
}

function AdjacentPages({ tabs, module, path }: { tabs: TabItem[]; module: ModuleId | undefined; path: string }) {
  const search = useRouterState({ select: (state) => state.location.search })
  const current = currentPage(tabs, module, path, search)
  const index = current ? tabs.indexOf(current) : -1
  if (tabs.length < 2 || index < 0) return null
  const previous = tabs[index - 1]
  const next = tabs[index + 1]
  const linkClass = 'inline-flex size-8 items-center justify-center rounded-md border text-muted-foreground hover:bg-hover hover:text-foreground'
  const disabledClass = 'inline-flex size-8 cursor-not-allowed items-center justify-center rounded-md border text-faint opacity-50'
  const link = (tab: TabItem, direction: 'Previous' | 'Next') => (
    <Link
      to={tab.to as never}
      params={tab.params as never}
      search={tab.search ? ((previousSearch: Record<string, unknown>) => ({ ...previousSearch, ...tab.search })) as never : undefined}
      className={linkClass}
      aria-label={`${direction} page: ${tab.label}`}
      title={`${direction}: ${tab.label}`}
    >
      {direction === 'Previous' ? <ChevronLeft className="size-4" /> : <ChevronRight className="size-4" />}
    </Link>
  )
  return (
    <div className="flex shrink-0 items-center gap-1 pb-1" aria-label="Previous and next pages">
      {previous ? link(previous, 'Previous') : <span className={disabledClass} aria-hidden="true"><ChevronLeft className="size-4" /></span>}
      {next ? link(next, 'Next') : <span className={disabledClass} aria-hidden="true"><ChevronRight className="size-4" /></span>}
    </div>
  )
}
