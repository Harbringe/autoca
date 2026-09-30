// One client's books inside a module: a header that says where they stand, and the module's tabs.
//
// The module comes from the address (Bank statements, Bookkeeping, Reports, or the client's own
// profile). Its tab row is only its own screens; the sidebar moves between modules. "Upload bank
// statement" is on every client page because it is where everything starts, and `u` does it too.

import { useQuery } from '@tanstack/react-query'
import { Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { Lock, Upload } from 'lucide-react'
import { booksStatus, clientDetail, reviewSummary } from '@/api/queries/clients'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { TabNav, type TabItem } from '@/components/ui/tabs'
import { BOOKS_STATE_HINT, BOOKS_STATE_LABEL, BOOKS_STATE_TONE, booksState, lockLabel } from '@/features/books/state'
import { UploadProvider, useUpload } from '@/features/statements/UploadDialog'
import { fyLabel } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { moduleOf, type ModuleId } from '@/lib/modules'
import { useFy } from '@/features/shell/useFy'
import { useSession } from '@/session/session'

const MODULE_TITLE: Partial<Record<ModuleId, string>> = {
  bank: 'Bank statements',
  bookkeeping: 'Bookkeeping',
  reports: 'Reports',
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

  const go = (to: string) => () => void navigate({ to: to as never, params: { clientId } as never })
  useHotkey('u', 'Upload a bank statement', () => can('document.upload') && upload.open(), 'This client')
  useHotkey('g o', 'Overview', go('/clients/$clientId'), 'Go to')
  useHotkey('g s', 'Statements', go('/clients/$clientId/statements'), 'Go to')
  useHotkey('g r', 'Review', go('/clients/$clientId/review'), 'Go to')
  useHotkey('g d', 'Day Book', go('/clients/$clientId/daybook'), 'Go to')
  useHotkey('g l', 'Ledgers', go('/clients/$clientId/ledgers'), 'Go to')
  useHotkey('g p', 'Reports', go('/clients/$clientId/reports'), 'Go to')
  useHotkey('g b', 'Books & sign-off', go('/clients/$clientId/books'), 'Go to')
  useHotkey('g e', 'Team and client details', () => (can('team.view') || can('client.update')) && go('/clients/$clientId/team')(), 'Go to')
  useHotkey('g m', 'Masters (ledgers, parties, rules)', go('/clients/$clientId/masters'), 'Go to')

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
            { to: '/clients/$clientId/daybook', params: p, label: 'Day Book' },
            { to: '/clients/$clientId/ledgers', params: p, label: 'Ledgers' },
            { to: '/clients/$clientId/masters', params: p, label: 'Parties & rules' },
            { to: '/clients/$clientId/books', params: p, label: 'Books & sign-off' },
          ]
        : module === 'clients'
          ? [
              { to: '/clients/$clientId', params: p, label: 'Overview', exact: true },
              ...(canTeam ? [{ to: '/clients/$clientId/team', params: p, label: 'Team & details' }] : []),
            ]
          : []
  const title = module && module !== 'clients' ? MODULE_TITLE[module] : client.data.name
  const upload_primary = module === 'clients' || module === 'bank'

  return (
    <div className="grid gap-4">
      <header className="no-print flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[26px] leading-8 xl:text-[28px] xl:leading-[34px]">{title}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm text-muted-foreground">
            {module === 'clients' ? (
              <span>{client.data.lead ? `${client.data.lead.name === 'Firm owner' ? 'Firm owner' : 'Senior CA'}: ${client.data.lead.name}` : 'No senior CA assigned'}</span>
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
        {can('document.upload') && (
          <Button variant={upload_primary ? 'primary' : 'secondary'} onClick={upload.open} className="max-sm:w-full">
            <Upload /> Upload bank statement
          </Button>
        )}
      </header>

      {tabs.length > 0 && <TabNav label={`${title} sections`} items={tabs} />}

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
