// One client's books: a header that says where they stand, and the work in the order it is done.
//
// Statements come in, rows are reviewed and placed, entries are posted to the Day Book, the
// reports are read, and the senior signs off. The tabs follow that order, the number beside
// each is how much is waiting there, and "Upload bank statement" is on every tab because it
// is where everything starts.

import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useNavigate } from '@tanstack/react-router'
import { Lock, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { booksStatus, clientDetail, reviewSummary } from '@/api/queries/clients'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { BOOKS_STATE_HINT, BOOKS_STATE_LABEL, BOOKS_STATE_TONE, booksState, lockLabel } from '@/features/books/state'
import { UploadProvider, useUpload } from '@/features/statements/UploadDialog'
import { fyLabel } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { useFy } from '@/features/shell/useFy'
import { useSession } from '@/session/session'

type Tab = {
  to:
    | '/clients/$clientId'
    | '/clients/$clientId/statements'
    | '/clients/$clientId/review'
    | '/clients/$clientId/daybook'
    | '/clients/$clientId/reports'
    | '/clients/$clientId/books'
    | '/clients/$clientId/masters'
    | '/clients/$clientId/team'
  label: string
  key: string
  count?: number
  exact?: boolean
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
  const upload = useUpload()
  const client = useQuery(clientDetail(clientId))
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  const books = useQuery({ ...booksStatus(clientId), enabled: can('report.view') })
  const { fy, setFy, explicit, ready, dataYears } = useFy()
  const latestYear = dataYears[dataYears.length - 1]

  const go = (to: Tab['to']) => () => void navigate({ to, params: { clientId } })
  useHotkey('u', 'Upload a bank statement', () => can('document.upload') && upload.open(), 'This client')
  useHotkey('g o', 'Overview', go('/clients/$clientId'), 'Go to')
  useHotkey('g s', 'Statements', go('/clients/$clientId/statements'), 'Go to')
  useHotkey('g r', 'Review', go('/clients/$clientId/review'), 'Go to')
  useHotkey('g d', 'Day Book', go('/clients/$clientId/daybook'), 'Go to')
  useHotkey('g p', 'Reports', go('/clients/$clientId/reports'), 'Go to')
  useHotkey('g b', 'Books & sign-off', go('/clients/$clientId/books'), 'Go to')
  useHotkey('g e', 'Team and client details', () => (can('team.view') || can('client.update')) && go('/clients/$clientId/team')(), 'Go to')
  useHotkey('g m', 'Masters (ledgers, parties, rules)', go('/clients/$clientId/masters'), 'Go to')

  if (client.isPending) return <Spinner label="Opening client…" />
  if (client.error) return <ErrorState error={client.error} retry={() => void client.refetch()} />

  const state = books.data ? booksState(books.data) : null
  const lock = books.data ? lockLabel(books.data) : null

  const tabs: Tab[] = [
    { to: '/clients/$clientId', label: 'Overview', key: 'o', exact: true },
    { to: '/clients/$clientId/statements', label: 'Statements', key: 's' },
    { to: '/clients/$clientId/review', label: 'Review', key: 'r', count: summary.data?.total },
    { to: '/clients/$clientId/daybook', label: 'Day Book', key: 'd' },
    { to: '/clients/$clientId/reports', label: 'Reports', key: 'p' },
    { to: '/clients/$clientId/books', label: 'Books & sign-off', key: 'b' },
    { to: '/clients/$clientId/masters', label: 'Masters', key: 'm' },
    ...(can('team.view') || can('client.update') ? [{ to: '/clients/$clientId/team', label: 'Team', key: 'e' } as Tab] : []),
  ]

  return (
    <div className="grid gap-4">
      <header className="no-print flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold leading-tight tracking-tight">{client.data.name}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>{client.data.lead ? `Senior CA: ${client.data.lead.name}` : 'No senior CA assigned'}</span>
            {state && (
              <Badge tone={BOOKS_STATE_TONE[state]} title={BOOKS_STATE_HINT[state]}>
                {BOOKS_STATE_LABEL[state]}
              </Badge>
            )}
            {lock && (
              <Badge tone="info">
                <Lock className="size-3" aria-hidden /> {lock}
              </Badge>
            )}
          </div>
        </div>
        {can('document.upload') && (
          <Button onClick={upload.open}>
            <Upload /> Upload bank statement
          </Button>
        )}
      </header>

      <nav aria-label="Client sections" className="no-print -mx-1 flex gap-1 overflow-x-auto border-b px-1">
        {tabs.map((tab) => (
          <TabLink key={tab.to} tab={tab} clientId={clientId}>
            {tab.label}
            {tab.count ? (
              <span className="rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-foreground">{tab.count}</span>
            ) : null}
          </TabLink>
        ))}
      </nav>

      {explicit && latestYear !== undefined && !dataYears.includes(fy) && (
        <p className="no-print -mt-2 text-[13px] text-muted-foreground">
          No statements or vouchers in FY {fyLabel(fy)}; this client’s data is in FY {dataYears.map(fyLabel).join(', FY ')}.{' '}
          <button type="button" className="font-medium text-primary underline underline-offset-2 dark:text-accent" onClick={() => setFy(latestYear)}>
            Show FY {fyLabel(latestYear)}
          </button>
        </p>
      )}

      {ready ? <Outlet /> : <Spinner label="Finding this client’s latest year…" />}
    </div>
  )
}

function TabLink({ tab, clientId, children }: { tab: Tab; clientId: string; children: ReactNode }) {
  return (
    <Link
      to={tab.to}
      params={{ clientId }}
      activeOptions={{ exact: !!tab.exact, includeSearch: false }}
      className="-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground data-[status=active]:border-primary data-[status=active]:text-foreground dark:data-[status=active]:border-accent"
    >
      {children}
    </Link>
  )
}
