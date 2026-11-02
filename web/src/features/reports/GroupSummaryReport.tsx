// Group Summary: each group's opening, debit, credit and closing for the year, with its ledgers. A ledger opens month by month.

import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { groupSummary, ledgerMonthly, type GroupRow } from '@/api/queries/books'
import { ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { formatPaise } from '@/lib/format'
import { ReportSkeleton } from './ReportPicture'

const money = (paise: number) => (paise === 0 ? '' : formatPaise(Math.abs(paise), { symbol: false }) + (paise < 0 ? ' Cr' : ' Dr'))
const amount = (paise: number) => (paise === 0 ? '' : formatPaise(paise, { symbol: false }))
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function LedgerMonths({ clientId, fy, ledgerId, onBack }: { clientId: string; fy: number; ledgerId: string; onBack: () => void }) {
  const query = useQuery(ledgerMonthly(clientId, fy, ledgerId))
  if (query.isPending) return <ReportSkeleton />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const d = query.data
  return (
    <div className="grid gap-2 text-sm">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to groups
        </Button>
        <h3 className="font-medium">
          {d.ledger.name} <span className="text-muted-foreground">({d.ledger.group_label})</span>
        </h3>
      </div>
      <table className="w-full" aria-label={`${d.ledger.name} by month`}>
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 font-medium">Month</th>
            <th className="py-1 text-right font-medium">Debit</th>
            <th className="py-1 text-right font-medium">Credit</th>
            <th className="py-1 text-right font-medium">Closing balance</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-border-strong">
            <td className="py-1">Opening</td>
            <td />
            <td />
            <td className="py-1 text-right tabular-nums">{money(d.opening_paise)}</td>
          </tr>
          {d.months.map((m) => (
            <tr key={m.month} className="border-t border-border-strong">
              <td className="py-1">{MONTHS[Number(m.month.split('-')[1]) - 1]} {m.month.split('-')[0]}</td>
              <td className="py-1 text-right tabular-nums">{amount(m.debit_paise)}</td>
              <td className="py-1 text-right tabular-nums">{amount(m.credit_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(m.closing_paise)}</td>
            </tr>
          ))}
          <tr className="border-t border-border-strong font-medium">
            <td className="py-1">Total</td>
            <td className="py-1 text-right tabular-nums">{amount(d.total_debit_paise)}</td>
            <td className="py-1 text-right tabular-nums">{amount(d.total_credit_paise)}</td>
            <td className="py-1 text-right tabular-nums">{money(d.closing_paise)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export function GroupSummaryReport({ clientId, fy }: { clientId: string; fy: number }) {
  const query = useQuery(groupSummary(clientId, fy))
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [ledger, setLedger] = useState<string | null>(null)
  if (query.isPending) return <ReportSkeleton />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  if (ledger) return <LedgerMonths clientId={clientId} fy={fy} ledgerId={ledger} onBack={() => setLedger(null)} />
  const d = query.data
  if (d.groups.length === 0) return <p className="text-sm text-muted-foreground">Nothing is booked for this year yet.</p>

  return (
    <table className="w-full text-sm" aria-label="Group summary">
      <thead>
        <tr className="text-left text-xs text-muted-foreground">
          <th className="py-1 font-medium">Group</th>
          <th className="py-1 text-right font-medium">Opening</th>
          <th className="py-1 text-right font-medium">Debit</th>
          <th className="py-1 text-right font-medium">Credit</th>
          <th className="py-1 text-right font-medium">Closing</th>
        </tr>
      </thead>
      <tbody>
        {d.groups.map((g) => (
          <GroupRows key={g.group} g={g} open={!!open[g.group]} toggle={() => setOpen({ ...open, [g.group]: !open[g.group] })} onLedger={setLedger} />
        ))}
        <tr className="border-t border-border-strong font-medium">
          <td className="py-1">Total</td>
          <td />
          <td className="py-1 text-right tabular-nums">{amount(d.total_debit_paise)}</td>
          <td className="py-1 text-right tabular-nums">{amount(d.total_credit_paise)}</td>
          <td />
        </tr>
      </tbody>
    </table>
  )
}

function GroupRows({ g, open, toggle, onLedger }: { g: GroupRow; open: boolean; toggle: () => void; onLedger: (id: string) => void }) {
  return (
    <>
      <tr className="border-t border-border-strong font-medium">
        <td className="py-1">
          <button type="button" className="flex items-center gap-1" aria-expanded={open} onClick={toggle}>
            <ChevronRight className={`size-4 transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden />
            {g.label}
          </button>
        </td>
        <td className="py-1 text-right tabular-nums">{money(g.opening_paise)}</td>
        <td className="py-1 text-right tabular-nums">{amount(g.debit_paise)}</td>
        <td className="py-1 text-right tabular-nums">{amount(g.credit_paise)}</td>
        <td className="py-1 text-right tabular-nums">{money(g.closing_paise)}</td>
      </tr>
      {open &&
        g.ledgers.map((l) => (
          <tr key={l.name} className="border-t border-border-strong text-muted-foreground">
            <td className="py-1 pl-6">
              {l.ledger_id ? (
                <button type="button" className="underline" onClick={() => onLedger(l.ledger_id!)}>
                  {l.name}
                </button>
              ) : (
                l.name
              )}
            </td>
            <td className="py-1 text-right tabular-nums">{money(l.opening_paise)}</td>
            <td className="py-1 text-right tabular-nums">{amount(l.debit_paise)}</td>
            <td className="py-1 text-right tabular-nums">{amount(l.credit_paise)}</td>
            <td className="py-1 text-right tabular-nums">{money(l.closing_paise)}</td>
          </tr>
        ))}
    </>
  )
}
