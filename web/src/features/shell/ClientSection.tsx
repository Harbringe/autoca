import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Building2, X } from 'lucide-react'
import { clientDetail } from '@/api/queries/clients'
import { CLIENT_NAV, clientScreenOf, clientScreenPath } from '@/lib/clientNav'
import { clientIdOf } from '@/lib/modules'
import { setSelectedClient } from '@/lib/selectedClient'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { usePalette } from './CommandPalette'

/** The selected client's own screens, so any of them is one click from anywhere in the app. */
export function ClientSection({ clientId, path, onNavigate }: { clientId: string; path: string; onNavigate?: () => void }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const current = clientScreenOf(path)
  const inClient = clientIdOf(path) === clientId
  const palette = usePalette()
  return (
    <div className="pt-2.5" role="group" aria-label="Selected client">
      <div className="mx-1 mb-1 flex items-center gap-1 rounded-md bg-white/5 px-2 py-1.5">
        <Building2 className="size-4 shrink-0 text-sidebar-muted" aria-hidden />
        <button type="button" onClick={() => palette.open()} className="min-w-0 flex-1 truncate text-left text-sm font-semibold text-white hover:underline" title="Change client">
          {client.data?.name ?? '…'}
        </button>
        <button type="button" onClick={() => setSelectedClient(null)} aria-label="Stop working on this client" title="Back to all clients" className="rounded p-1 text-sidebar-muted hover:bg-white/10 hover:text-white">
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      {CLIENT_NAV.map((group) => {
        const screens = group.screens.filter((item) => can(item.permission))
        if (screens.length === 0) return null
        return (
          <div key={group.label} className="pt-1.5">
            <div className="px-3 pb-0.5 text-[11px] font-medium uppercase tracking-wide text-sidebar-muted">{group.label}</div>
            <ul className="grid gap-0.5">
              {screens.map((item) => {
                const isActive = inClient && current === item.screen
                return (
                  <li key={item.screen || 'overview'}>
                    <Link
                      to={clientScreenPath(clientId, item.screen) as never}
                      onClick={onNavigate}
                      aria-current={isActive ? 'page' : undefined}
                      className={cn(
                        'relative flex h-8 items-center rounded-md px-3 text-sm font-medium text-sidebar-foreground hover:bg-white/5 hover:text-white',
                        isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-bar',
                      )}
                    >
                      <span className="truncate">{item.label}</span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
      <div className="mx-3 mt-3 border-t border-white/10" />
    </div>
  )
}
