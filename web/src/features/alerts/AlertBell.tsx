import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Bell, CheckCircle2 } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'
import { messageOf } from '@/api/errors'
import { firmAlerts } from '@/api/queries/alerts'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { AlertRow, SEVERITY_LABEL } from './AlertList'
import { badgeText, filterAlerts, severityCounts, type SeverityFilter } from './alertView'

/** How many things need attention across the firm, kept current. Zero while it loads or is not allowed. */
export function useAlertCount(): number {
  const { can } = useSession()
  const feed = useQuery({ ...firmAlerts(), enabled: can('client.view') })
  return feed.data?.counts.total ?? 0
}

const TABS: { id: SeverityFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'critical', label: SEVERITY_LABEL.critical },
  { id: 'high', label: SEVERITY_LABEL.high },
  { id: 'medium', label: SEVERITY_LABEL.medium },
]

/**
 * The bell in the top bar. It opens a panel under itself listing what needs attention, most serious
 * first; choosing a row goes to the screen where it is fixed and closes the panel.
 */
export function AlertBell() {
  const { can } = useSession()
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<SeverityFilter>('all')
  const feed = useQuery({ ...firmAlerts(), enabled: can('client.view') })
  if (!can('client.view')) return null

  const alerts = feed.data?.alerts ?? []
  const count = feed.data?.counts.total ?? 0
  const counts = severityCounts(alerts)
  const visible = filterAlerts(alerts, filter)
  const close = () => setOpen(false)

  // Up and Down walk the rows, Home and End jump; Esc and focus return are the popover's own.
  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
    const rows = [...e.currentTarget.querySelectorAll<HTMLElement>('[data-alert-row]')]
    if (rows.length === 0) return
    const at = rows.indexOf(document.activeElement as HTMLElement)
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? rows.length - 1 : e.key === 'ArrowDown' ? Math.min(at + 1, rows.length - 1) : Math.max(at - 1, 0)
    e.preventDefault()
    rows[next]?.focus()
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-haspopup="dialog"
          aria-label={count ? `Alerts: ${count} need attention` : 'Alerts: nothing needs attention'}
          title="Alerts"
        >
          <Bell className="size-[18px]" aria-hidden />
          {count > 0 && (
            <span className="num absolute right-0.5 top-0.5 grid min-w-4 place-items-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-4 text-white">
              {badgeText(count)}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" aria-label="Alerts" className="w-[380px] max-w-[calc(100vw-1rem)] max-sm:w-[calc(100vw-1rem)]">
        <div className="flex items-baseline justify-between gap-3 px-4 pb-1 pt-3">
          <h2 className="text-sm font-semibold text-heading">
            Alerts {count > 0 && <span className="num font-normal text-muted-foreground">({count})</span>}
          </h2>
        </div>
        {alerts.length > 0 && (
          <div role="group" aria-label="Filter by severity" className="flex flex-wrap gap-1.5 px-4 pb-2">
            {TABS.filter((t) => t.id === 'all' || counts[t.id] > 0 || filter === t.id).map((t) => (
              <button
                key={t.id}
                type="button"
                aria-pressed={filter === t.id}
                onClick={() => setFilter(t.id)}
                className={cn(
                  'inline-flex h-8 items-center gap-1 rounded-full border px-3 text-[13px] font-medium',
                  filter === t.id ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-foreground hover:bg-hover',
                )}
              >
                {t.label} <span className="num">{counts[t.id]}</span>
              </button>
            ))}
          </div>
        )}
        <div className="max-h-[min(70vh,28rem)] overflow-y-auto overscroll-contain border-t" onKeyDown={onListKey}>
          {feed.error ? (
            <div role="alert" className="grid justify-items-start gap-2 p-4 text-sm">
              <p>{messageOf(feed.error)}</p>
              <Button variant="outline" size="sm" onClick={() => void feed.refetch()}>
                Try again
              </Button>
            </div>
          ) : !feed.data ? (
            <div aria-busy="true" aria-label="Loading alerts" className="grid gap-3 p-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton h-12 rounded-md" />
              ))}
            </div>
          ) : visible.length === 0 ? (
            <div className="grid justify-items-center gap-1 p-8 text-center">
              <CheckCircle2 className="size-6 text-success" aria-hidden />
              <p className="text-sm font-semibold text-heading">All clear</p>
              <p className="text-[13px] text-muted-foreground">{alerts.length ? 'Nothing at this level.' : 'Nothing needs a person right now.'}</p>
            </div>
          ) : (
            <ul className="divide-y">
              {visible.map((alert, i) => (
                <AlertRow key={`${alert.client}-${alert.kind}-${alert.to}-${i}`} alert={alert} onNavigate={close} />
              ))}
            </ul>
          )}
        </div>
        <div className="border-t px-4 py-2.5 text-sm">
          <Link to="/alerts" onClick={close} className="font-medium text-link underline underline-offset-2">
            View all alerts
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  )
}
