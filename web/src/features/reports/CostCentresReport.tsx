// Income and expense by cost centre for the year, and where the client's cost centres are kept. Lines are tagged from the Day Book.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { messageOf } from '@/api/errors'
import { costCentreReport, useMakeCostCentre, useRemoveCostCentre } from '@/api/queries/analysis'
import { ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatPaise } from '@/lib/format'
import { toast } from '@/lib/toast'
import { useSession } from '@/session/session'
import { ReportSkeleton } from './ReportPicture'

const money = (paise: number) => (paise === 0 ? '–' : formatPaise(paise, { symbol: false }))

export function CostCentresReport({ clientId, fy }: { clientId: string; fy: number }) {
  const { can } = useSession()
  const query = useQuery(costCentreReport(clientId, fy))
  const make = useMakeCostCentre(clientId)
  const remove = useRemoveCostCentre(clientId)
  const [name, setName] = useState('')
  if (query.isPending) return <ReportSkeleton />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const d = query.data
  const mayManage = can('ledger.manage')

  return (
    <div className="grid gap-4 text-sm">
      {mayManage && (
        <div className="flex gap-2">
          <Input aria-label="Cost centre name" className="max-w-xs" placeholder="e.g. Pune site" value={name} onChange={(e) => setName(e.target.value)} />
          <Button
            variant="outline"
            disabled={!name.trim() || make.isPending}
            onClick={() => make.mutate(name, { onSuccess: () => setName(''), onError: (e) => toast.error(messageOf(e)) })}
          >
            Add cost centre
          </Button>
        </div>
      )}
      {d.centres.length === 0 ? (
        <p className="text-muted-foreground">No cost centres yet. Add one, then tag income and expense lines to it from a voucher in the Day Book.</p>
      ) : (
        <table className="w-full" aria-label="By cost centre">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 font-medium">Cost centre</th>
              <th className="py-1 text-right font-medium">Income</th>
              <th className="py-1 text-right font-medium">Expense</th>
              <th className="py-1 text-right font-medium">Net</th>
              {mayManage && <th className="py-1" />}
            </tr>
          </thead>
          <tbody>
            {d.centres.map((c) => (
              <tr key={c.id} className="border-t border-border-strong align-top">
                <td className="py-1">
                  {c.name}
                  {c.ledgers.length > 0 && <span className="block text-xs text-muted-foreground">{c.ledgers.map((l) => `${l.ledger} ${money(l.amount_paise)}`).join(' · ')}</span>}
                </td>
                <td className="py-1 text-right tabular-nums">{money(c.income_paise)}</td>
                <td className="py-1 text-right tabular-nums">{money(c.expense_paise)}</td>
                <td className="py-1 text-right tabular-nums">{money(c.net_paise)}</td>
                {mayManage && (
                  <td className="py-1 text-right">
                    <Button size="sm" variant="ghost" aria-label={`Remove ${c.name}`} onClick={() => remove.mutate(c.id, { onError: (e) => toast.error(messageOf(e)) })}>
                      Remove
                    </Button>
                  </td>
                )}
              </tr>
            ))}
            <tr className="border-t border-border-strong text-muted-foreground">
              <td className="py-1">Not tagged to any cost centre</td>
              <td className="py-1 text-right tabular-nums">{money(d.unallocated_income_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(d.unallocated_expense_paise)}</td>
              <td />
              {mayManage && <td />}
            </tr>
          </tbody>
        </table>
      )}
    </div>
  )
}
