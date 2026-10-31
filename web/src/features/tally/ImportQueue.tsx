// The client's queue of Tally imports: every file ever read for the client, whether it still waits to be posted, is being posted, was
// posted or was taken back. The file itself stays with the client's documents, so an import from years ago can be opened again, and
// a waiting import can be read again against today's ledgers without uploading it a second time.

import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { V1 } from '@/api/queries/clients'
import { voucherRuns, type VoucherRunSummary } from '@/api/queries/tallyImport'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'

function stateOf(run: VoucherRunSummary): { label: string; tone: string } {
  if (run.status === 'CONFIRMED') return { label: 'Posted', tone: 'text-success' }
  if (run.status === 'DISCARDED') return { label: (run.result?.undone ?? 0) > 0 ? 'Taken back' : 'Discarded', tone: 'text-muted-foreground' }
  if (run.posting) {
    const p = run.progress
    return { label: p ? `Posting ${p.done} of ${p.total}` : 'Posting', tone: 'text-heading' }
  }
  if (run.error) return { label: 'Could not post', tone: 'text-danger' }
  return { label: 'Waiting to be posted', tone: 'text-heading' }
}

export function ImportQueue({ clientId, onOpen, openId }: { clientId: string; onOpen: (id: string) => void; openId?: string }) {
  const runs = useQuery({
    ...voucherRuns(clientId),
    // While any import is being posted the list keeps itself up to date; otherwise it is read when the screen opens.
    refetchInterval: (query) => (query.state.data?.some((r) => r.posting) ? 2500 : false),
  })
  if (runs.isPending) return <Spinner />
  if (runs.error || !runs.data?.length) return null

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Imports</h2>
      <p className="text-sm text-muted-foreground">
        Every file read for this client stays here, with the file itself in the client's documents. A waiting import is posted when you choose.
      </p>
      <ul aria-label="Imports" className="divide-y divide-border-strong rounded-lg border border-border-strong">
        {runs.data.map((run) => {
          const state = stateOf(run)
          return (
            <li key={run.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-3 py-2 text-sm">
              <div className="min-w-0 flex-1 basis-64">
                <p className="truncate font-medium">{run.file_name || 'Tally import'}</p>
                <p className="text-xs text-muted-foreground">
                  {plural(run.counts.vouchers, 'voucher')} · {run.counts.date_from} to {run.counts.date_to} · read {formatDate(run.created_at.slice(0, 10))}
                  {run.uploaded_by_name ? ` by ${run.uploaded_by_name}` : ''}
                </p>
              </div>
              <span className={state.tone}>{state.label}</span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant={openId === run.id ? 'secondary' : 'outline'} onClick={() => onOpen(run.id)}>
                  Open
                </Button>
                {run.document && (
                  <Button asChild size="sm" variant="ghost" aria-label={`Download ${run.file_name}`}>
                    <a href={`${V1}/documents/${run.document}/download/`}>
                      <Download />
                    </a>
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
