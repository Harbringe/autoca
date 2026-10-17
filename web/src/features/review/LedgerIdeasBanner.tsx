// "The assistant has ledger ideas for N rows": one button to open the ledgers that do not exist yet and place every row that carries an idea,
// instead of opening each row and creating each ledger by hand. It asks first, listing what it will do, and says what it did.

import { Link } from '@tanstack/react-router'
import { Bot, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { V1, useInvalidateClient } from '@/api/queries/clients'
import type { Classification, LedgerAccount } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Button } from '@/components/ui/button'
import { plural } from '@/lib/format'
import { toast } from '@/lib/toast'
import { ideasOf, runLimited, type Idea } from './ledgerIdeas'

const AT_A_TIME = 4
const LISTED = 8

/** One box for the assistant's new-ledger work: the ledgers it already opened (sure enough to act, names to check) and the ideas it only suggests (nothing opened until a person says yes). */
export function LedgerIdeasBanner({
  clientId,
  rows,
  canPlace,
  canCreate,
  proposed = [],
  showIdeas = true,
}: {
  clientId: string
  rows: readonly Classification[]
  canPlace: boolean
  canCreate: boolean
  proposed?: readonly { id: string; name: string }[]
  showIdeas?: boolean
}) {
  const invalidate = useInvalidateClient(clientId)
  const ideas = useMemo(() => ideasOf(rows), [rows])
  const [asking, setAsking] = useState(false)
  const [progress, setProgress] = useState<string | null>(null)
  const total = ideas.reduce((n, i) => n + i.rows.length, 0)
  const toCreate = ideas.filter((i) => !i.existingLedger)
  // Opening a ledger is a separate permission from placing rows; without it only the ideas for ledgers that exist can be used.
  const usable = canCreate ? ideas : ideas.filter((i) => i.existingLedger)
  const usableRows = usable.reduce((n, i) => n + i.rows.length, 0)
  const hasIdeas = showIdeas && canPlace && ideas.length > 0
  if (!hasIdeas && proposed.length === 0) return null

  async function apply() {
    let placed = 0
    let failed = 0
    let opened = 0
    for (const idea of usable) {
      let ledger = idea.existingLedger
      if (!ledger) {
        try {
          const made = await raw.post<LedgerAccount>(`${V1}/clients/${clientId}/ledgers/`, { name: idea.name.trim(), group: idea.group })
          ledger = made.id
          opened += 1
        } catch (e) {
          failed += idea.rows.length
          toast.error(`Could not open “${idea.name}”`, { description: messageOf(e) })
          continue
        }
      }
      const target = ledger
      const result = await runLimited(
        idea.rows.map((r) => () =>
          raw.post(`${V1}/classifications/${r.id}/review/`, {
            ledger: target,
            party: null,
            rcm: false,
            tds_section: '',
            // A row with a payee teaches the rule, as placing it by hand does; a transfer to oneself does not.
            learn: !!r.counterparty && !r.is_self_transfer,
          }),
        ),
        AT_A_TIME,
        (done, bad) => setProgress(`Placing ${placed + done + bad} of ${usableRows}…`),
      )
      placed += result.done
      failed += result.failed
    }
    setProgress(null)
    await invalidate()
    if (placed) toast.success(`${plural(placed, 'row')} placed${opened ? `, ${plural(opened, 'new ledger')} opened` : ''}`, { description: 'They are in Ready to post, for you to check and post.' })
    if (failed) toast.error(`${plural(failed, 'row')} could not be placed`, { description: 'They are still in this list.' })
  }

  const listed = usable.slice(0, LISTED)
  return (
    <>
      <div className="grid divide-y divide-info/20 rounded-xl border border-info/30 bg-info-bg text-sm text-info">
        {proposed.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <span>
              <Bot className="mr-1.5 inline size-4" aria-hidden />
              <b className="mr-1.5 rounded-md bg-info/15 px-1.5 py-0.5 text-xs font-semibold">Added</b>
              {plural(proposed.length, 'new ledger')} opened ({proposed.slice(0, 3).map((l) => l.name).join(', ')}
              {proposed.length > 3 ? '…' : ''}). Check each name.
            </span>
            <Button asChild size="sm" variant="outline">
              <Link to="/clients/$clientId/ledgers" params={{ clientId }}>
                Look at them
              </Link>
            </Button>
          </div>
        )}
        {hasIdeas && (
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <span>
              <Sparkles className="mr-1.5 inline size-4" aria-hidden />
              <b className="mr-1.5 rounded-md border border-dashed border-info/50 px-1.5 py-0.5 text-xs font-semibold">Idea</b>
              The assistant has a ledger idea for <b>{plural(total, 'row')}</b>
              {toCreate.length > 0 ? ` (${plural(toCreate.length, 'new ledger')} to open, not opened yet)` : ''}. You can use them all at once.
            </span>
            <Button size="sm" variant="outline" disabled={usableRows === 0 || progress !== null} onClick={() => setAsking(true)}>
              {progress ?? `Use all ${plural(usableRows, 'idea')}…`}
            </Button>
          </div>
        )}
      </div>
      <Confirm
        open={asking}
        onOpenChange={setAsking}
        title={`Use the assistant’s ideas for ${plural(usableRows, 'row')}?`}
        confirmLabel={`Place ${usableRows}`}
        busyLabel="Placing…"
        onConfirm={apply}
      >
        <p>
          {plural(usable.filter((i) => !i.existingLedger).length, 'ledger')} will be opened, and each row is placed in the ledger it carries an idea for. Nothing is
          posted: the rows move to Ready to post, where you check them.
        </p>
        <ul className="grid gap-1 text-sm">
          {listed.map((i: Idea) => (
            <li key={i.key} className="flex justify-between gap-3">
              <span className="truncate">
                <b className="font-medium">{i.name}</b> <span className="text-muted-foreground">{i.existingLedger ? '(exists)' : '(new)'}</span>
              </span>
              <span className="num shrink-0">{plural(i.rows.length, 'row')}</span>
            </li>
          ))}
          {usable.length > LISTED && <li className="text-muted-foreground">and {usable.length - LISTED} more</li>}
        </ul>
        {!canCreate && toCreate.length > 0 && <p className="text-muted-foreground">{plural(toCreate.length, 'idea')} need a new ledger, which your role cannot open; they are left for someone who can.</p>}
      </Confirm>
    </>
  )
}
