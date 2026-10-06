// Every alert across the clients the person may see, most serious first. Each row opens the screen
// where it is fixed. The chips narrow it by module; the counts on them always cover everything.

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { firmAlerts } from '@/api/queries/alerts'
import type { AlertModule } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { cn } from '@/lib/utils'
import { usePageTitle } from '@/lib/title'
import { AlertList, MODULE_LABEL } from './AlertList'
import { sortAlerts } from './alertView'

export interface AlertsSearch {
  module?: AlertModule
  client?: string
}

const MODULES = Object.keys(MODULE_LABEL) as AlertModule[]

export function parseAlertsSearch(search: Record<string, unknown>): AlertsSearch {
  const module = MODULES.find((m) => m === search.module)
  const client = typeof search.client === 'string' && search.client ? search.client : undefined
  return { module, client }
}

export function AlertsScreen({ search }: { search: AlertsSearch }) {
  usePageTitle('Alerts')
  const navigate = useNavigate()
  const feed = useQuery(firmAlerts())
  const choose = (module?: AlertModule) => void navigate({ to: '/alerts', search: { module, client: search.client } as never, replace: true })

  if (feed.error) return <ErrorState error={feed.error} retry={() => void feed.refetch()} />
  if (feed.isLoading || !feed.data) return <div className="skeleton h-64 rounded-lg" aria-busy="true" aria-label="Loading alerts" />

  const { counts } = feed.data
  const alerts = sortAlerts(feed.data.alerts).filter((a) => (!search.module || a.module === search.module) && (!search.client || a.client === search.client))
  const chip = (active: boolean) =>
    cn('inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium', active ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-foreground hover:bg-hover')

  return (
    <div className="grid gap-5">
      <PageHeader
        title="Alerts"
        description={counts.total ? `${counts.total} things need attention, most serious first. Select one to go straight to where it is fixed.` : 'Nothing needs attention right now.'}
      />
      <div role="group" aria-label="Filter by module" className="flex flex-wrap gap-2">
        <button type="button" className={chip(!search.module)} aria-pressed={!search.module} onClick={() => choose(undefined)}>
          All <span className="num">{counts.total}</span>
        </button>
        {MODULES.filter((m) => (counts.by_module[m] ?? 0) > 0 || search.module === m).map((m) => (
          <button key={m} type="button" className={chip(search.module === m)} aria-pressed={search.module === m} onClick={() => choose(m)}>
            {MODULE_LABEL[m]} <span className="num">{counts.by_module[m] ?? 0}</span>
          </button>
        ))}
      </div>
      {alerts.length === 0 ? (
        <EmptyState title="All clear">Nothing here needs a person. New alerts appear as statements arrive and deadlines come close.</EmptyState>
      ) : (
        <AlertList alerts={alerts} className="max-w-4xl" />
      )}
    </div>
  )
}
