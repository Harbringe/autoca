// Budget against the books: each budgeted ledger month by month, and where a ledger's budget is set.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { messageOf } from '@/api/errors'
import { budgetVariance, useSetBudget } from '@/api/queries/analysis'
import { ledgers as ledgersQuery } from '@/api/queries/books'
import { ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatPaise, parseRupees } from '@/lib/format'
import { toast } from '@/lib/toast'
import { useSession } from '@/session/session'
import { ReportSkeleton } from './ReportPicture'

const money = (paise: number | null) => (paise === null || paise === 0 ? '–' : formatPaise(paise, { symbol: false }))
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const order = (fy: number) => [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3].map((m) => `${m >= 4 ? fy : fy + 1}-${String(m).padStart(2, '0')}`)

function Editor({ clientId, fy }: { clientId: string; fy: number }) {
  const ledgers = useQuery(ledgersQuery(clientId))
  const save = useSetBudget(clientId)
  const [ledger, setLedger] = useState('')
  const [text, setText] = useState<Record<string, string>>({})
  const usable = (ledgers.data ?? []).filter((l) => l.status === 'ACTIVE')

  function submit() {
    const months: Record<string, number | null> = {}
    for (const m of order(fy)) {
      const value = (text[m] ?? '').trim()
      if (!value) continue
      const paise = parseRupees(value)
      if (paise === null) return void toast.error('Amounts are in rupees, like 25000 or 25000.50.')
      months[m] = paise
    }
    if (!ledger || Object.keys(months).length === 0) return void toast.error('Pick a ledger and give at least one month.')
    save.mutate({ fy, ledger, months }, { onSuccess: () => toast.success('Budget saved'), onError: (e) => toast.error(messageOf(e)) })
  }

  return (
    <div className="grid gap-2 rounded-md border border-line p-3">
      <h4 className="font-medium">Set a budget</h4>
      <label className="grid gap-0.5 text-xs text-muted-foreground">
        <span>Ledger to budget</span>
        <select aria-label="Ledger to budget" className="h-9 max-w-sm rounded-md border border-border-strong bg-transparent px-2 text-sm text-foreground" value={ledger} onChange={(e) => setLedger(e.target.value)}>
          <option value="">Choose a ledger</option>
          {usable.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap gap-2">
        {order(fy).map((m) => (
          <label key={m} className="grid gap-0.5 text-xs text-muted-foreground">
            <span aria-hidden>{MONTHS[Number(m.split('-')[1]) - 1]}</span>
            <Input aria-label={`Budget for ${m}`} inputMode="decimal" className="w-24" value={text[m] ?? ''} onChange={(e) => setText({ ...text, [m]: e.target.value })} />
          </label>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">A month left empty is kept as it was.</p>
      <div>
        <Button loading={save.isPending} onClick={submit}>
          Save budget
        </Button>
      </div>
    </div>
  )
}

export function BudgetReport({ clientId, fy }: { clientId: string; fy: number }) {
  const { can } = useSession()
  const query = useQuery(budgetVariance(clientId, fy))
  if (query.isPending) return <ReportSkeleton />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const d = query.data

  return (
    <div className="grid gap-4 text-sm">
      {d.ledgers.length === 0 ? (
        <p className="text-muted-foreground">No budget is set for this year yet.</p>
      ) : (
        d.ledgers.map((l) => (
          <table key={l.ledger_id} className="w-full" aria-label={`Budget for ${l.ledger}`}>
            <caption className="pb-1 text-left font-medium">
              {l.ledger} <span className="text-muted-foreground">({l.is_income ? 'income: above budget is good' : 'expense: above budget is overspending'})</span>
            </caption>
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 font-medium">Month</th>
                <th className="py-1 text-right font-medium">Budget</th>
                <th className="py-1 text-right font-medium">Actual</th>
                <th className="py-1 text-right font-medium">Variance</th>
              </tr>
            </thead>
            <tbody>
              {l.months.map((m) => (
                <tr key={m.month} className="border-t border-border-strong">
                  <td className="py-1">{MONTHS[Number(m.month.split('-')[1]) - 1]} {m.month.split('-')[0]}</td>
                  <td className="py-1 text-right tabular-nums">{money(m.budget_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{money(m.actual_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{m.budget_paise === null ? '' : money(m.variance_paise)}</td>
                </tr>
              ))}
              <tr className="border-t border-border-strong font-medium">
                <td className="py-1">Year</td>
                <td className="py-1 text-right tabular-nums">{money(l.budget_paise)}</td>
                <td className="py-1 text-right tabular-nums">{money(l.actual_paise)}</td>
                <td className="py-1 text-right tabular-nums">{money(l.variance_paise)}</td>
              </tr>
            </tbody>
          </table>
        ))
      )}
      {can('ledger.manage') && <Editor clientId={clientId} fy={fy} />}
    </div>
  )
}
