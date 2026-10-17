// The ledgers the assistant added, for a senior CA to look at: paged like every other list, tick any or all of them (across pages),
// and keep the ticked ones in one go, each with the group the assistant gave it or one chosen for all of them. Merging or rejecting a
// ledger is a decision about that one ledger, so it stays on its own row ("Decide").

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Bot } from 'lucide-react'
import { raw } from '@/api/client'
import { ledgerRows } from '@/api/queries/books'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import { GROUP_LABEL, LEDGER_GROUPS, type LedgerAccount } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { PagedList } from '@/components/ca/Pager'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox, Select } from '@/components/ui/controls'
import { DataTable } from '@/components/ui/table'
import { runLimited } from '@/features/review/ledgerIdeas'
import { formatDate, plural } from '@/lib/format'
import { toast } from '@/lib/toast'

/** How many ledgers are kept at once. A few at a time: quick, and kind to the server. */
const AT_ONCE = 4
/** How many of a ledger's rows the preview lists. */
const PREVIEW_ROWS = 50

/** The rows that sit in one ledger the assistant added, so a person can see what was sent where before keeping or merging it. */
function RowsPreview({ clientId, ledger }: { clientId: string; ledger: LedgerAccount }) {
  const rows = useQuery(ledgerRows(clientId, ledger.id))
  const list = rows.data ?? []
  return (
    <div className="grid gap-2 rounded-md border bg-card px-3 py-2 text-sm" aria-live="polite">
      <div className="font-medium text-heading">Rows in {ledger.name}</div>
      {rows.isPending ? (
        <p className="text-muted-foreground">Loading the rows…</p>
      ) : rows.isError ? (
        <p className="text-destructive">The rows could not be loaded.</p>
      ) : list.length === 0 ? (
        <p className="text-muted-foreground">No rows are in this ledger yet.</p>
      ) : (
        <ul className="grid gap-1 text-xs">
          {list.slice(0, PREVIEW_ROWS).map((r) => (
            <li key={r.id} className="grid grid-cols-[5.5rem_minmax(0,1fr)_7rem_5.5rem] gap-2">
              <span className="text-muted-foreground">{formatDate(r.value_date)}</span>
              <span className="truncate" title={r.narration}>
                {r.counterparty || r.narration}
              </span>
              <span className="num text-right">
                {r.amount_display} {r.is_debit ? 'Dr' : 'Cr'}
              </span>
              <span className="text-muted-foreground">{r.is_posted ? 'Posted' : 'Waiting'}</span>
            </li>
          ))}
          {list.length > PREVIEW_ROWS && <li className="text-muted-foreground">and {list.length - PREVIEW_ROWS} more</li>}
        </ul>
      )}
    </div>
  )
}

export function ProposedLedgers({ clientId, proposed, mayDecide, onDecide }: { clientId: string; proposed: LedgerAccount[]; mayDecide: boolean; onDecide: (l: LedgerAccount) => void }) {
  const invalidate = useInvalidateClient(clientId)
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  // '' keeps each ledger in the group the assistant gave it.
  const [group, setGroup] = useState('')
  const [asking, setAsking] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)

  const chosen = proposed.filter((l) => ticked.has(l.id))
  const allTicked = proposed.length > 0 && chosen.length === proposed.length
  const toggle = (id: string, on: boolean) =>
    setTicked((cur) => {
      const next = new Set(cur)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  async function keepChosen() {
    const { done, failed } = await runLimited(
      chosen.map((l) => () => raw.post(`${V1}/clients/${clientId}/ledgers/${l.id}/accept/`, { name: l.name, group: group || l.group })),
      AT_ONCE,
    )
    setTicked(new Set())
    await invalidate()
    if (failed) toast.error(`${plural(done, 'ledger')} kept; ${failed} could not be, and are still listed.`)
    else toast.success(`${plural(done, 'ledger')} kept`)
  }

  return (
    <Card className="grid gap-3 border-info/40 p-4">
      <div className="flex items-center gap-2 font-medium">
        <Bot className="size-4 text-info" aria-hidden /> Ledgers the assistant added ({proposed.length})
      </div>
      <p className="text-sm text-muted-foreground">
        {mayDecide
          ? 'Keep each with the exact name it has in Tally, or merge it into a ledger that already exists. Ledgers the assistant added are live already, so rows may be in them; a merge moves those rows across.'
          : 'A senior CA who leads this client decides these.'}
      </p>
      {mayDecide && proposed.length > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-card px-3 py-2 text-sm">
          <Checkbox label={`Select all ${proposed.length}`} checked={allTicked} onChange={(e) => setTicked(e.target.checked ? new Set(proposed.map((l) => l.id)) : new Set())} />
          <span className="text-muted-foreground" aria-live="polite">{chosen.length ? `${chosen.length} selected` : 'Nothing selected yet'}</span>
        </div>
      )}
      <PagedList rows={proposed} resetKey="proposed" label="ledgers the assistant added" section="proposals">
        {(shown) => (
          <DataTable
            caption="Ledgers the assistant added"
            rows={shown}
            rowKey={(l) => l.id}
            columns={[
              ...(mayDecide
                ? [{ key: 'pick', header: <span className="sr-only">Select</span>, cell: (l: LedgerAccount) => <Checkbox checked={ticked.has(l.id)} onChange={(e) => toggle(l.id, e.target.checked)} aria-label={`Select ${l.name}`} /> }]
                : []),
              { key: 'name', header: 'Name', cell: (l: LedgerAccount) => <span className="font-medium text-heading">{l.name}</span> },
              { key: 'group', header: 'Group', priority: 2, cell: (l: LedgerAccount) => GROUP_LABEL[l.group ?? ''] ?? l.group },
              { key: 'why', header: 'Why', priority: 3, className: 'max-w-md truncate text-muted-foreground', cell: (l: LedgerAccount) => l.proposal_reason },
              { key: 'rows', header: 'Rows', align: 'right' as const, cell: (l: LedgerAccount) => l.row_count },
              {
                key: 'act',
                header: <span className="sr-only">Actions</span>,
                align: 'right' as const,
                cell: (l: LedgerAccount) => (
                  <span className="inline-flex gap-1.5">
                    <Button size="sm" variant="ghost" onClick={() => setPreviewId(previewId === l.id ? null : l.id)} aria-expanded={previewId === l.id} aria-label={`Preview the rows in ${l.name}`}>
                      {previewId === l.id ? 'Hide rows' : 'Preview rows'}
                    </Button>
                    {mayDecide && (
                      <Button size="sm" variant="outline" onClick={() => onDecide(l)} aria-label={`Decide on ${l.name}`}>
                        Decide
                      </Button>
                    )}
                  </span>
                ),
              },
            ]}
          />
        )}
      </PagedList>
      {previewId && proposed.find((l) => l.id === previewId) && <RowsPreview clientId={clientId} ledger={proposed.find((l) => l.id === previewId)!} />}
      {mayDecide && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Select aria-label="Group for the selected ledgers" className="w-72" value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">Keep each in its suggested group</option>
            {LEDGER_GROUPS.map(([g, l]) => (
              <option key={g} value={g}>{l}</option>
            ))}
          </Select>
          <Button disabled={chosen.length === 0} onClick={() => setAsking(true)}>
            Keep {chosen.length ? plural(chosen.length, 'ledger') : 'selected'}
          </Button>
        </div>
      )}
      <Confirm
        open={asking}
        onOpenChange={setAsking}
        title={`Keep ${plural(chosen.length, 'ledger')}?`}
        confirmLabel={`Keep ${chosen.length}`}
        busyLabel="Keeping…"
        onConfirm={keepChosen}
      >
        <p className="text-sm text-muted-foreground">
          Each is kept with the name it has now{group ? `, in ${GROUP_LABEL[group] ?? group}` : ', in the group the assistant gave it'}. Check the names are exactly as in Tally; a ledger can be renamed afterwards. Nothing is merged or rejected.
        </p>
      </Confirm>
    </Card>
  )
}
