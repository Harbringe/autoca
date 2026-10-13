// Every alert across the clients the person may see, as an inbox: the list on the left, the selected alert on the right. The module and the client
// are in the address, so the links from a module's banner and from the bell land on the right list.

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { firmAlerts } from '@/api/queries/alerts'
import type { AlertModule } from '@/api/types'
import { ErrorState, PageHeader } from '@/components/ca/Page'
import { plural } from '@/lib/format'
import { usePageTitle } from '@/lib/title'
import { AlertsInbox } from './AlertsInbox'
import { MODULE_LABEL } from './AlertList'
import { clientsOf } from './alertView'

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
  const filter = (next: AlertsSearch) => void navigate({ to: '/alerts', search: next as never, replace: true })

  if (feed.error) return <ErrorState error={feed.error} retry={() => void feed.refetch()} />
  if (feed.isLoading || !feed.data) return <div className="skeleton h-64 rounded-lg" aria-busy="true" aria-label="Loading alerts" />

  const alerts = feed.data.alerts
  const clients = clientsOf(alerts).length
  return (
    <div className="grid gap-4">
      <PageHeader
        title="Alerts"
        description={alerts.length ? `${plural(alerts.length, 'alert')}${clients > 1 ? ` across ${plural(clients, 'client')}` : ''}` : undefined}
        className="mb-0"
      />
      <AlertsInbox alerts={alerts} filter={search} onFilter={filter} />
    </div>
  )
}
