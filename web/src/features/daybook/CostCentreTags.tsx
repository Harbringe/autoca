// Tag a voucher's income and expense lines to a cost centre. The books are not changed; only how the year is read by cost centre.

import { useQuery } from '@tanstack/react-query'
import { costCentres, entryTags, useTagLine } from '@/api/queries/analysis'
import { messageOf } from '@/api/errors'
import type { JournalEntry } from '@/api/types'
import { formatPaise } from '@/lib/format'
import { toast } from '@/lib/toast'

const PL_GROUPS = new Set(['INDIRECT_EXPENSE', 'DIRECT_EXPENSE', 'INDIRECT_INCOME', 'DIRECT_INCOME', 'SALES', 'PURCHASE'])

export function CostCentreTags({ clientId, entry, mayTag }: { clientId: string; entry: JournalEntry; mayTag: boolean }) {
  const centres = useQuery(costCentres(clientId))
  const tags = useQuery(entryTags(clientId, String(entry.id)))
  const tag = useTagLine(clientId)
  const lines = entry.lines.filter((l) => PL_GROUPS.has(String((l as { ledger_group?: string }).ledger_group ?? '')))
  if (!centres.data || centres.data.length === 0 || lines.length === 0) return null

  return (
    <section className="grid gap-2 text-sm" aria-label="Cost centres">
      <span className="text-muted-foreground">Cost centre</span>
      {lines.map((l) => {
        const mine = (tags.data ?? []).filter((t) => t.line === String(l.id))
        const current = mine.length === 1 && mine[0]!.amount_paise === l.amount_paise ? mine[0]!.cost_centre : mine.length > 0 ? 'split' : ''
        return (
          <label key={String(l.id)} className="flex flex-wrap items-center gap-2">
            <span className="w-56">
              {l.ledger_name} <span className="text-muted-foreground">{formatPaise(l.amount_paise, { symbol: false })}</span>
            </span>
            <select
              aria-label={`Cost centre for ${l.ledger_name}`}
              className="h-9 rounded-md border border-border-strong bg-transparent px-2"
              value={current}
              disabled={!mayTag || tag.isPending}
              onChange={(e) =>
                tag.mutate(
                  { line: String(l.id), allocations: e.target.value && e.target.value !== 'split' ? [{ cost_centre: e.target.value, amount_paise: l.amount_paise }] : [] },
                  { onError: (err) => toast.error(messageOf(err)) },
                )
              }
            >
              <option value="">None</option>
              {current === 'split' && <option value="split">Split across centres</option>}
              {centres.data!.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        )
      })}
    </section>
  )
}
