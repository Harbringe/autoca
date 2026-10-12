// The year in figures on a client's overview: money by month, the biggest costs, who owes whom. Each card
// reads the same server snapshot as the bookkeeping page, so a figure here can never differ from a report,
// and each card loads and fails on its own. Not drawn at all for a person who may not read the books.

import { useQuery } from '@tanstack/react-query'
import { clientSnapshot } from '@/api/queries/dashboard'
import { useFy } from '@/features/shell/useFy'
import { useSession } from '@/session/session'
import { CostsCard, MonthlyCard, OwedCard } from './FinancialSnapshot'

export function OverviewReports({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const { fy } = useFy()
  const on = can('journal.view')
  const snapshot = useQuery({ ...clientSnapshot(clientId, fy), enabled: on })
  if (!on) return null
  return (
    <section aria-labelledby="year-title" className="grid gap-3">
      <h2 id="year-title" className="text-[15px] font-semibold text-heading">
        The year in figures
      </h2>
      <div className="grid gap-4 lg:grid-cols-5 lg:items-start [&>*]:min-w-0">
        <div className="lg:col-span-3">
          <MonthlyCard query={snapshot} clientId={clientId} />
        </div>
        <div className="lg:col-span-2">
          <CostsCard query={snapshot} clientId={clientId} />
        </div>
        <div className="lg:col-span-5">
          <OwedCard query={snapshot} clientId={clientId} />
        </div>
      </div>
    </section>
  )
}
