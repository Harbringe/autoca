// Alerts as rows, each one a link to the screen where it is fixed. Used by the Alerts page, by the
// banner at the top of every module, and by the bell's panel.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, ChevronRight, CircleX, X } from 'lucide-react'
import { useState } from 'react'
import { clientAlerts, firmAlerts } from '@/api/queries/alerts'
import type { Alert, AlertModule } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
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
 * firm otherwise. One "View alerts" button, right-aligned, with the count; it opens a panel listing
 * every alert here, most serious first, each row a link to where it is fixed. Says nothing at all
 * when there is nothing, so a clean module stays quiet.
 */
export function ModuleAlerts({ module, clientId }: { module: AlertModule; clientId?: string }) {
  const one = useQuery({ ...clientAlerts(clientId ?? '', module), enabled: !!clientId })
  const all = useQuery({ ...firmAlerts(module), enabled: !clientId })
  const feed = clientId ? one.data : all.data
  const alerts = sortAlerts(feed?.alerts ?? [])
  const [open, setOpen] = useState(false)
  if (alerts.length === 0) return null
  const urgent = alerts.filter((a) => a.severity === 'critical').length
  return (
    <section aria-label={`Alerts for ${MODULE_LABEL[module]}`} className="no-print flex justify-end">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" aria-haspopup="dialog" className="max-sm:h-10">
            <AlertTriangle className={cn('size-4', urgent > 0 ? 'text-destructive' : 'text-accent-foreground')} aria-hidden />
            View alerts <span className="num">({alerts.length})</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" aria-label={`Alerts for ${MODULE_LABEL[module]}`} className="w-[420px] max-w-[calc(100vw-1rem)]">
          <div className="flex items-center justify-between gap-3 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-heading">
              Alerts <span className="num font-normal text-muted-foreground">({alerts.length})</span>
              {urgent > 0 && <span className="num font-normal text-destructive"> · {urgent} urgent</span>}
            </h2>
            <PopoverClose asChild>
              <Button variant="ghost" size="icon" className="-mr-2 max-sm:size-11" aria-label="Close alerts">
                <X className="size-4" aria-hidden />
              </Button>
            </PopoverClose>
          </div>
          <ul className="max-h-[min(60vh,26rem)] divide-y overflow-y-auto overscroll-contain border-t">
            {alerts.map((alert, i) => (
              <AlertRow key={`${alert.client}-${alert.kind}-${alert.to}-${i}`} alert={alert} showClient={!clientId} onNavigate={() => setOpen(false)} />
            ))}
          </ul>
          <div className="border-t px-4 py-3 text-sm">
            <Link
              to="/alerts"
              search={(clientId ? { client: clientId, module } : { module }) as never}
              onClick={() => setOpen(false)}
              className="font-medium text-link underline underline-offset-2"
            >
              All alerts
            </Link>
          </div>
        </PopoverContent>
      </Popover>
    </section>
  )
}
