// Alerts as rows, each one a link to the screen where it is fixed. Used by the Alerts page, by the
// panel at the top of every module, and anywhere else something needs a person.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronRight } from 'lucide-react'
import { clientAlerts, firmAlerts } from '@/api/queries/alerts'
import type { Alert, AlertModule } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export const SEVERITY_LABEL: Record<Alert['severity'], string> = { critical: 'Urgent', high: 'Important', medium: 'To do' }
const SEVERITY_TONE = { critical: 'danger', high: 'attention', medium: 'neutral' } as const

export const MODULE_LABEL: Record<AlertModule, string> = {
  bank: 'Bank statements',
  bookkeeping: 'Bookkeeping',
  reports: 'Reports',
  gst: 'GST',
  documents: 'Documents',
}

export function AlertRow({ alert, showClient = true }: { alert: Alert; showClient?: boolean }) {
  return (
    <li>
      <Link
        to={alert.to as never}
        search={alert.search as never}
        className="group flex items-center gap-3 px-4 py-3 text-sm hover:bg-hover focus-visible:bg-hover"
      >
        <Badge tone={SEVERITY_TONE[alert.severity]} className="shrink-0">
          {SEVERITY_LABEL[alert.severity]}
        </Badge>
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-heading">
            {showClient && <span className="text-muted-foreground">{alert.client_name} · </span>}
            {alert.title}
          </span>
          <span className="block text-[13px] text-muted-foreground">{alert.detail}</span>
        </span>
        <ChevronRight className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" aria-hidden />
      </Link>
    </li>
  )
}

export function AlertList({ alerts, showClient = true, className }: { alerts: Alert[]; showClient?: boolean; className?: string }) {
  return (
    <ul className={cn('divide-y rounded-lg border bg-card', className)}>
      {alerts.map((alert, i) => (
        <AlertRow key={`${alert.client}-${alert.kind}-${alert.to}-${i}`} alert={alert} showClient={showClient} />
      ))}
    </ul>
  )
}

/**
 * What needs attention inside one module: for one client when `clientId` is given, for the whole
 * firm otherwise. Says nothing at all when there is nothing, so a clean module stays quiet.
 */
export function ModuleAlerts({ module, clientId }: { module: AlertModule; clientId?: string }) {
  const one = useQuery({ ...clientAlerts(clientId ?? '', module), enabled: !!clientId })
  const all = useQuery({ ...firmAlerts(module), enabled: !clientId })
  const feed = clientId ? one.data : all.data
  const alerts = feed?.alerts ?? []
  if (alerts.length === 0) return null
  const shown = alerts.slice(0, 5)
  return (
    <section aria-label={`Alerts for ${MODULE_LABEL[module]}`} className="no-print grid gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-heading">
          Needs attention <span className="num font-normal text-muted-foreground">({alerts.length})</span>
        </h2>
        <Link to="/alerts" search={(clientId ? { client: clientId, module } : { module }) as never} className="text-[13px] text-link underline underline-offset-2">
          All alerts
        </Link>
      </div>
      <AlertList alerts={shown} showClient={!clientId} />
      {alerts.length > shown.length && <p className="text-xs text-muted-foreground">And {alerts.length - shown.length} more.</p>}
    </section>
  )
}
