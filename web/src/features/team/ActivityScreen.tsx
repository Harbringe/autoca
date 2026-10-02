// Activity log: every change anyone made in the firm, in words, newest first. Read-only.
// The server turns each request into a sentence and names the client it touched.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { AUDIT_PAGE, auditLog } from '@/api/queries/audit'
import type { AuditRow } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/controls'
import { DataTable, type Column } from '@/components/ui/table'
import { formatDateTime } from '@/lib/format'
import { usePageTitle } from '@/lib/title'
import { useSession } from '@/session/session'

const columns: Column<AuditRow>[] = [
  { key: 'at', header: 'When', cell: (r) => <span className="num whitespace-nowrap text-muted-foreground">{formatDateTime(r.at)}</span> },
  { key: 'who', header: 'Who', cell: (r) => <span title={r.email ?? undefined}>{r.who}</span> },
  {
    key: 'action',
    header: 'What happened',
    cell: (r) =>
      r.client_id ? (
        <Link to="/clients/$clientId" params={{ clientId: r.client_id }} className="hover:underline">
          {r.action}
        </Link>
      ) : (
        r.action
      ),
  },
  {
    key: 'outcome',
    header: 'Outcome',
    priority: 2,
    cell: (r) => (r.succeeded ? <Badge tone="done">Done</Badge> : <Badge tone="danger">Refused ({r.status_code})</Badge>),
  },
]

export function ActivityScreen() {
  usePageTitle('Activity log')
  const { can } = useSession()
  const [page, setPage] = useState(1)
  const [failed, setFailed] = useState(false)
  const log = useQuery({ ...auditLog(page, failed), enabled: can('audit.view') })
  if (!can('audit.view')) return <EmptyState title="Not available">The activity log is for firm administrators.</EmptyState>
  if (log.error) return <ErrorState error={log.error} retry={() => void log.refetch()} />
  const pages = Math.max(1, Math.ceil((log.data?.count ?? 0) / AUDIT_PAGE))
  return (
    <div className="grid gap-3">
      <PageHeader title="Activity log" description="Who changed what, and when. It cannot be edited or deleted." className="mb-0" />
      <Checkbox
        label="Only requests that were refused"
        checked={failed}
        onChange={(e) => {
          setFailed(e.target.checked)
          setPage(1)
        }}
      />
      <DataTable
        caption="Activity log"
        columns={columns}
        rows={log.data?.results}
        loading={log.isLoading}
        rowKey={(r) => r.id}
        empty={<EmptyState title="Nothing recorded">{failed ? 'No refused requests.' : 'Changes made in the firm appear here.'}</EmptyState>}
      />
      {log.data && log.data.count > AUDIT_PAGE && (
        <nav aria-label="Activity log pages" className="flex items-center justify-between gap-3 text-sm">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Newer
          </Button>
          <span className="num text-muted-foreground" aria-live="polite">
            Page {page} of {pages}
          </span>
          <Button variant="outline" size="sm" disabled={!log.data.next} onClick={() => setPage(page + 1)}>
            Older
          </Button>
        </nav>
      )}
    </div>
  )
}
