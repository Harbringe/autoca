import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Bell } from 'lucide-react'
import { firmAlerts } from '@/api/queries/alerts'
import { useSession } from '@/session/session'

/** How many things need attention across the firm, kept current. Zero while it loads or is not allowed. */
export function useAlertCount(): number {
  const { can } = useSession()
  const feed = useQuery({ ...firmAlerts(), enabled: can('client.view') })
  return feed.data?.counts.total ?? 0
}

/** The bell in the top bar: a count, and one click to the alerts page. */
export function AlertBell() {
  const { can } = useSession()
  const count = useAlertCount()
  if (!can('client.view')) return null
  return (
    <Link
      to="/alerts"
      className="relative grid size-9 place-items-center rounded-md text-muted-foreground hover:bg-hover hover:text-foreground"
      aria-label={count ? `Alerts: ${count} need attention` : 'Alerts: nothing needs attention'}
      title="Alerts"
    >
      <Bell className="size-[18px]" aria-hidden />
      {count > 0 && (
        <span className="num absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-4 text-white">
          {count > 99 ? '99+' : count}
        </span>
      )}
    </Link>
  )
}
