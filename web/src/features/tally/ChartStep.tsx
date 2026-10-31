// Step 1 of a Tally import: the client's chart of accounts and opening balances. Choose the masters file and the year its balances are
// as at, read the preview, settle every line that needs a decision (nothing is assumed), then apply. Vouchers come after this: a
// voucher naming a ledger that is not in the chart is left out.

import { useRef, useState } from 'react'
import { CheckCircle2, FileUp } from 'lucide-react'
import { useConfirmMasters, useStageMasters, type MastersRow, type MastersRun, type Resolution } from '@/api/queries/tallyImport'
import { LEDGER_GROUPS } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox, Select } from '@/components/ui/controls'
import { plural } from '@/lib/format'
import { toast } from '@/lib/toast'

const messageOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'Something went wrong. Try again.')

const CHOICE_LABEL: Record<string, string> = {
  keep_ours: 'Keep ours as it is',
  take_tally: "Take Tally's group",
  use_tally_name: "Rename ours to Tally's spelling",
  use_this_spelling: 'Use this spelling',
  group: 'Put it in one of our groups',
  skip: 'Leave it out',
  use_tally: "Use Tally's opening",
  keep_bank: 'Keep the bank account as it is',
}

/** The year that starts the Indian financial year the person is probably importing: this one, or last once April has just begun. */
const defaultYear = () => {
  const now = new Date()
  return now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1
}

interface Pick {
  choice?: string
  group?: string
  bank?: string
}

const needsChoice = (r: MastersRow) => r.action === 'conflict' || r.action === 'needs_group'
const needsBank = (r: MastersRow) => r.bank?.status === 'conflict'

function startingPicks(run: MastersRun): Record<number, Pick> {
  const picks: Record<number, Pick> = {}
  for (const r of run.rows) {
    const pick: Pick = {}
    if (needsChoice(r) && r.conflict?.default) pick.choice = r.conflict.default
    if (needsBank(r) && r.bank?.default) pick.bank = r.bank.default
    if (Object.keys(pick).length) picks[r.row] = pick
  }
  return picks
}

const isSettled = (r: MastersRow, pick: Pick | undefined) =>
  (!needsChoice(r) || (!!pick?.choice && (pick.choice !== 'group' || !!pick.group))) && (!needsBank(r) || !!pick?.bank)

export function ChartStep({ clientId }: { clientId: string }) {
  const stage = useStageMasters(clientId)
  const confirm = useConfirmMasters(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [year, setYear] = useState(defaultYear())
  const [openings, setOpenings] = useState(true)
  const [run, setRun] = useState<MastersRun | null>(null)
  const [picks, setPicks] = useState<Record<number, Pick>>({})
  const [error, setError] = useState<string | null>(null)

  async function choose(file: File | undefined) {
    if (!file) return
    setError(null)
    setRun(null)
    try {
      const staged = await stage.mutateAsync({ file, financialYear: year, includeOpenings: openings })
      setRun(staged)
      setPicks(startingPicks(staged))
    } catch (e) {
      setError(messageOf(e))
    }
  }

  const deciding = run?.rows.filter((r) => needsChoice(r) || needsBank(r)) ?? []
  const unsettled = deciding.filter((r) => !isSettled(r, picks[r.row]))
  const setPick = (row: number, patch: Pick) => setPicks((cur) => ({ ...cur, [row]: { ...cur[row], ...patch } }))

  async function apply() {
    if (!run) return
    setError(null)
    const resolutions: Resolution[] = deciding.map((r) => ({ row: r.row, ...picks[r.row] }))
    try {
      const done = await confirm.mutateAsync({ runId: run.id, resolutions })
      setRun(done)
      toast.success(`${plural(done.result?.created ?? 0, 'ledger')} added`)
    } catch (e) {
      setError(messageOf(e))
    }
  }

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">1. The client's ledgers</h2>
      <p className="text-sm text-muted-foreground">
        Choose the ledgers (masters) exported from Tally: an .xml, .json, .xlsx or .csv. Their groups and opening balances come in with them. Nothing is
        changed until you apply the preview.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">
          Balances are as at 1 April
          <input
            type="number"
            aria-label="Year the balances are as at"
            className="h-9 w-28 rounded-md border border-input bg-card px-2"
            value={year}
            min={2000}
            max={2100}
            onChange={(e) => setYear(Number(e.target.value))}
          />
        </label>
        <Checkbox label="Bring in the opening balances too" checked={openings} onChange={(e) => setOpenings(e.target.checked)} />
        <input
          ref={input}
          type="file"
          accept=".xml,.json,.xlsx,.csv"
          aria-label="Ledgers file"
          className="sr-only"
          onChange={(e) => {
            void choose(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        <Button variant="outline" loading={stage.isPending} onClick={() => input.current?.click()}>
          <FileUp aria-hidden /> Choose the ledgers file
        </Button>
      </div>

      {error && (
        <Card tone="danger" role="alert" className="p-3 text-sm">
          {error}
        </Card>
      )}

      {run && run.status === 'PREVIEW' && (
        <div className="grid gap-3">
          <p className="text-sm" data-testid="chart-counts">
            {run.counts.create} new, {run.counts.match} already there, {run.counts.conflict + run.counts.needs_group} to decide, {run.counts.skipped} left out.
            {openings ? ` Opening balances differ by ${run.counts.difference_display}.` : ''}
          </p>
          {deciding.length > 0 && (
            <ul className="grid gap-2">
              {deciding.map((r) => {
                const pick = picks[r.row]
                return (
                  <li key={r.row} className="grid gap-2 rounded border p-3 text-sm">
                    <div>
                      <span className="font-medium">{r.name}</span> <span className="text-muted-foreground">({r.tally_group})</span>
                      {r.ledger_name && r.ledger_name !== r.name && <span className="text-muted-foreground"> — close to our {r.ledger_name}</span>}
                    </div>
                    {needsChoice(r) && (
                      <div className="flex flex-wrap gap-2">
                        <Select
                          aria-label={`What to do with ${r.name}`}
                          className="w-72"
                          value={pick?.choice ?? ''}
                          onChange={(e) => setPick(r.row, { choice: e.target.value })}
                        >
                          <option value="">Choose…</option>
                          {(r.conflict?.choices ?? ['group', 'skip']).map((c) => (
                            <option key={c} value={c}>
                              {CHOICE_LABEL[c] ?? c}
                            </option>
                          ))}
                        </Select>
                        {pick?.choice === 'group' && (
                          <Select aria-label={`Our group for ${r.name}`} className="w-56" value={pick.group ?? ''} onChange={(e) => setPick(r.row, { group: e.target.value })}>
                            <option value="">Which group…</option>
                            {LEDGER_GROUPS.map(([g, l]) => (
                              <option key={g} value={g}>
                                {l}
                              </option>
                            ))}
                          </Select>
                        )}
                      </div>
                    )}
                    {needsBank(r) && r.bank && (
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-muted-foreground">{r.bank.label}: the bank account and Tally disagree on the opening balance.</span>
                        <Select aria-label={`Opening balance for ${r.bank.label}`} className="w-64" value={pick?.bank ?? ''} onChange={(e) => setPick(r.row, { bank: e.target.value })}>
                          <option value="">Choose…</option>
                          {r.bank.choices.map((c) => (
                            <option key={c} value={c}>
                              {CHOICE_LABEL[c] ?? c}
                            </option>
                          ))}
                        </Select>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          <div>
            <Button loading={confirm.isPending} disabled={unsettled.length > 0} onClick={() => void apply()}>
              Apply the ledgers
            </Button>
            {unsettled.length > 0 && <span className="ml-3 text-sm text-muted-foreground">{plural(unsettled.length, 'line')} still need your choice.</span>}
          </div>
        </div>
      )}

      {run && run.status === 'CONFIRMED' && run.result && (
        <div className="flex items-center gap-2 text-sm font-medium">
          <CheckCircle2 className="size-4 text-success" aria-hidden />
          {plural(run.result.created, 'ledger')} added, {run.result.matched} already there, {plural(run.result.openings, 'opening balance')} stored. The vouchers can be imported now.
        </div>
      )}
    </Card>
  )
}
