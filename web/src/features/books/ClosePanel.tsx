// Before you sign off: every control and open item for this client, on one panel.
//
// Controls (rows posted, assistant entries checked, nothing in Suspense, each bank account against its statement) show as
// passing or failing. Open items where the books and a document or the bank disagree block sign-off until they are fixed or
// a senior writes why they can stand; that reason is kept with the item. The rest are listed so they are seen, not gated.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CircleCheck, CircleX } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { closeReport, useExplainItem, useWithdrawExplanation } from '@/api/queries/bills'
import type { CloseItem } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { plural } from '@/lib/format'

export function ClosePanel({ clientId, maySignOff }: { clientId: string; maySignOff: boolean }) {
  const report = useQuery(closeReport(clientId))
  const explain = useExplainItem(clientId)
  const withdraw = useWithdrawExplanation(clientId)
  const [writing, setWriting] = useState<string | null>(null)
  const [note, setNote] = useState('')

  if (report.isPending) return <Spinner label="Checking what is open…" />
  if (report.isError) return <ErrorState error={report.error} retry={() => void report.refetch()} />
  const { checks, items, unexplained_blocking: unexplained } = report.data
  const blocking = items.filter((i) => i.blocking)
  const others = items.filter((i) => !i.blocking)
  const failing = checks.filter((c) => !c.ok)

  async function save(item: CloseItem) {
    try {
      await explain.mutateAsync({ itemKey: item.key, note })
      toast.success('Reason saved')
      setWriting(null)
      setNote('')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function unsay(item: CloseItem) {
    try {
      await withdraw.mutateAsync(item.key)
      toast.success('Reason withdrawn')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  return (
    <Card className="grid gap-4 p-5" aria-labelledby="close-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="close-heading" className="text-base font-semibold">Before you sign off</h2>
        <Badge tone={report.data.ready ? 'done' : 'attention'}>
          {report.data.ready
            ? 'Everything ties out'
            : failing.length
              ? `${plural(failing.length, 'control')} failing`
              : `${plural(unexplained, 'blocking item')} to fix or explain`}
        </Badge>
      </div>

      <ul className="grid gap-1 text-sm">
        {checks.map((c) => (
          <li key={c.name} className={c.ok ? 'flex items-start gap-2 text-success' : 'flex items-start gap-2 text-destructive'}>
            {c.ok ? <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden /> : <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden />}
            <span>
              {c.title}
              {!c.ok && c.detail && <span className="block text-muted-foreground">{c.detail}</span>}
            </span>
          </li>
        ))}
      </ul>

      {blocking.length > 0 && (
        <div className="grid gap-2">
          <h3 className="text-sm font-medium">Open items that block sign-off</h3>
          <ul className="grid gap-2">
            {blocking.map((item) => (
              <li key={item.key} className="grid gap-1 rounded-md border bg-card p-3 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-muted-foreground">{item.title}</div>
                    <div>{item.summary}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {item.amount_display && <Money display={item.amount_display} />}
                    {item.explained ? <Badge tone="done">Explained</Badge> : <Badge tone="attention">Open</Badge>}
                  </div>
                </div>
                {item.explained ? (
                  <div className="flex flex-wrap items-center justify-between gap-2 text-muted-foreground">
                    <span>
                      “{item.note}”{item.explained_by && ` · ${item.explained_by}`}
                    </span>
                    {maySignOff && (
                      <Button variant="ghost" size="sm" onClick={() => void unsay(item)}>
                        Withdraw
                      </Button>
                    )}
                  </div>
                ) : maySignOff && writing === item.key ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Input aria-label="Why this can stand" className="min-w-64 flex-1" placeholder="Why this can stand" value={note} onChange={(e) => setNote(e.target.value)} />
                    <Button size="sm" disabled={note.trim().length < 5 || explain.isPending} onClick={() => void save(item)}>
                      Save reason
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setWriting(null)}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  maySignOff && (
                    <div>
                      <Button variant="outline" size="sm" onClick={() => { setWriting(item.key); setNote('') }}>
                        Explain why it can stand
                      </Button>
                    </div>
                  )
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {others.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {plural(others.length, 'other open item')} do not block sign-off.{' '}
          <Link to="/clients/$clientId/open-items" params={{ clientId }} className="underline">
            See them under To fix
          </Link>
          .
        </p>
      )}
    </Card>
  )
}
