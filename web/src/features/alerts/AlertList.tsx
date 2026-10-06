// Alerts as rows, each one a link to the screen where it is fixed. Used by the Alerts page, by the
// banner at the top of every module, and by the bell's panel.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, ChevronDown, ChevronRight, CircleX } from 'lucide-react'
import { useState } from 'react'
import { clientAlerts, firmAlerts } from '@/api/queries/alerts'
import type { Alert, AlertModule } from '@/api/types'
import { cn } from '@/lib/utils'
import { sortAlerts } from './alertView'

export const SEVERITY_LABEL: Record<Alert['severity'], string> = { critical: 'Urgent', high: 'Important', medium: 'To do' }

export const MODULE_LABEL: Record<AlertModule, string> = {
  bank: 'Bank statements',
  bookkeeping: 'Bookkeeping',
  reports: 'Reports',
  gst: 'GST',
  documents: 'Documents',
}

const SEVERITY_TEXT: Record<Alert['severity'], string> = { critical: 'text-destructive', high: 'text-accent-foreground', medium: 'text-muted-foreground' }

/** Severity as a small shape and a word, so it never rests on colour. */
export function SeverityMark({ severity, className }: { severity: Alert['severity']; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap text-xs font-semibold', SEVERITY_TEXT[severity], className)}>
      {severity === 'critical' ? (
        <CircleX className="size-3.5 shrink-0" aria-hidden />
      ) : severity === 'high' ? (
        <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
      ) : (
        <span className="mx-1 size-1.5 shrink-0 rounded-full bg-current" aria-hidden />
      )}
      {SEVERITY_LABEL[severity]}
    </span>
  )
}

/**
 * One alert: severity, what is wrong, for whom, in a line of detail. The whole row is the link.
 * `onNavigate` lets a panel close itself when the row is chosen.
 */
export function AlertRow({ alert, showClient = true, onNavigate, className }: { alert: Alert; showClient?: boolean; onNavigate?: () => void; className?: string }) {
  return (
    <li>
      <Link
        to={alert.to as never}
        search={alert.search as never}
        onClick={onNavigate}
        data-alert-row
        className={cn('group flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-hover focus-visible:bg-hover', className)}
      >
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <SeverityMark severity={alert.severity} />
            {showClient && <span className="min-w-0 truncate text-xs text-muted-foreground">{alert.client_name}</span>}
          </span>
          <span className="mt-0.5 block font-medium text-heading">{alert.title}</span>
          <span className="line-clamp-2 text-[13px] text-muted-foreground">{alert.detail}</span>
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
        <AlertRow key={`${alert.client}-${alert.kind}-${alert.to}-${i}`} alert={alert} showClient={showClient} className="py-3" />
      ))}
    </ul>
  )
}

/**
 * What needs attention inside one module: for one client when `clientId` is given, for the whole
 * firm otherwise. One slim line that opens to the list; open from the start only when there are one
 * or two. Says nothing at all when there is nothing, so a clean module stays quiet.
 */
export function ModuleAlerts({ module, clientId }: { module: AlertModule; clientId?: string }) {
  const one = useQuery({ ...clientAlerts(clientId ?? '', module), enabled: !!clientId })
  const all = useQuery({ ...firmAlerts(module), enabled: !clientId })
  const feed = clientId ? one.data : all.data
  const alerts = sortAlerts(feed?.alerts ?? [])
  const [chosen, setChosen] = useState<boolean | undefined>(undefined)
  if (alerts.length === 0) return null
  const open = chosen ?? alerts.length <= 2
  const shown = alerts.slice(0, 8)
  const urgent = alerts.filter((a) => a.severity === 'critical').length
  return (
    <section aria-label={`Alerts for ${MODULE_LABEL[module]}`} className="no-print overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center gap-2 px-3">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setChosen(!open)}
          className="flex h-10 min-w-0 flex-1 items-center gap-2 text-left text-sm font-medium text-heading"
        >
          {open ? <ChevronDown className="size-4 shrink-0" aria-hidden /> : <ChevronRight className="size-4 shrink-0" aria-hidden />}
          <AlertTriangle className="size-4 shrink-0 text-accent-foreground" aria-hidden />
          <span className="truncate">
            <span className="num">{alerts.length}</span> {alerts.length === 1 ? 'thing needs' : 'things need'} attention
            {urgent > 0 && <span className="num font-normal text-destructive"> ({urgent} urgent)</span>}
          </span>
        </button>
        <Link to="/alerts" search={(clientId ? { client: clientId, module } : { module }) as never} className="shrink-0 text-[13px] text-link underline underline-offset-2">
          All alerts
        </Link>
      </div>
      {open && (
        <ul className="divide-y border-t">
          {shown.map((alert, i) => (
            <AlertRow key={`${alert.client}-${alert.kind}-${alert.to}-${i}`} alert={alert} showClient={!clientId} className="py-2" />
          ))}
          {alerts.length > shown.length && <li className="px-4 py-2 text-xs text-muted-foreground">And {alerts.length - shown.length} more in All alerts.</li>}
        </ul>
      )}
    </section>
  )
}
