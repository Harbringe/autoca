import { createFileRoute } from '@tanstack/react-router'
import { WorkScreen, type WorkSearch } from '@/features/work/WorkScreen'
import type { PeriodKey } from '@/lib/period'

const PERIODS: PeriodKey[] = ['month', 'last', 'fy', 'custom']
const ISO = /^\d{4}-\d{2}-\d{2}$/
const text = (v: unknown) => (typeof v === 'string' && v ? v : undefined)

export const Route = createFileRoute('/_app/work')({
  validateSearch: (search: Record<string, unknown>): WorkSearch => ({
    period: PERIODS.includes(search.period as PeriodKey) ? (search.period as PeriodKey) : undefined,
    from: typeof search.from === 'string' && ISO.test(search.from) ? search.from : undefined,
    to: typeof search.to === 'string' && ISO.test(search.to) ? search.to : undefined,
    member: text(search.member),
  }),
  component: Screen,
})

function Screen() {
  return <WorkScreen search={Route.useSearch()} />
}
