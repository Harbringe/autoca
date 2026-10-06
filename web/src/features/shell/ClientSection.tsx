import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Building2, ChevronRight, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { clientDetail } from '@/api/queries/clients'
import { CLIENT_NAV, clientScreenOf, clientScreenPath } from '@/lib/clientNav'
import { clientIdOf } from '@/lib/modules'
import { setSelectedClient } from '@/lib/selectedClient'
import { openClientGroups } from '@/lib/sidebarNav'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { usePalette } from './CommandPalette'

const chip = 'num ml-auto rounded-sm bg-sidebar-chip px-1.5 text-xs font-medium text-sidebar-chip-foreground'

/**
 * The selected client's own screens, in groups that fold. The group holding the current screen and the
 * first group start open, so the menu is short and the screen you are on is always in view.
 */
export function ClientSection({ clientId, path, reviewCount, onNavigate }: { clientId: string; path: string; reviewCount?: number; onNavigate?: () => void }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const inClient = clientIdOf(path) === clientId
  const current = inClient ? clientScreenOf(path) : undefined
  const palette = usePalette()
  const [open, setOpen] = useState<string[]>(() => openClientGroups(CLIENT_NAV, current))
  // Going to a screen opens its group, and leaves the rest as the person set them.
  useEffect(() => {
    const wanted = openClientGroups(CLIENT_NAV, current)
    setOpen((prev) => (wanted.every((l) => prev.includes(l)) ? prev : [...new Set([...prev, ...wanted])]))
  }, [current])
  const toggle = (label: string) => setOpen((prev) => (prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]))

  return (
    <section aria-label="Selected client" className="pt-2">
      <div className="mb-1 flex items-center gap-1 rounded-md bg-white/5 px-2 py-1">
        <Building2 className="size-4 shrink-0 text-sidebar-muted" aria-hidden />
        <button
          type="button"
          onClick={() => palette.open()}
          className="h-8 min-w-0 flex-1 truncate rounded text-left text-sm font-semibold text-white hover:underline"
          title="Change client"
          aria-label={`Client ${client.data?.name ?? ''}. Change client`}
        >
          {client.data?.name ?? '…'}
        </button>
        <button
          type="button"
          onClick={() => setSelectedClient(null)}
          aria-label="Stop working on this client"
          title="Back to all clients"
          className="grid size-8 shrink-0 place-items-center rounded text-sidebar-muted hover:bg-white/10 hover:text-white"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      {CLIENT_NAV.map((group) => {
        const screens = group.screens.filter((item) => can(item.permission))
        if (screens.length === 0) return null
        const isOpen = open.includes(group.label)
        const listId = `client-nav-${group.label.replace(/\W+/g, '-').toLowerCase()}`
        return (
          <div key={group.label}>
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={listId}
              onClick={() => toggle(group.label)}
              className="flex h-8 w-full items-center gap-1 rounded-md px-3 text-xs font-medium text-sidebar-muted hover:bg-white/5 hover:text-white"
            >
              <ChevronRight className={cn('size-3 shrink-0 transition-transform', isOpen && 'rotate-90')} aria-hidden />
              {group.label}
            </button>
            {isOpen && (
              <ul id={listId} className="grid gap-0.5 pb-1">
                {screens.map((item) => {
                  const isActive = current === item.screen
                  return (
                    <li key={item.screen || 'overview'}>
                      <Link
                        to={clientScreenPath(clientId, item.screen) as never}
                        onClick={onNavigate}
                        aria-current={isActive ? 'page' : undefined}
                        className={cn(
                          'relative flex h-8 items-center rounded-md pl-7 pr-3 text-sm font-medium text-sidebar-foreground hover:bg-white/5 hover:text-white',
                          isActive && 'bg-sidebar-active text-white before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-bar',
                        )}
                      >
                        <span className="truncate">{item.label}</span>
                        {item.screen === 'review' && reviewCount ? (
                          <span className={chip} title="Rows waiting for this client">
                            {reviewCount}
                          </span>
                        ) : null}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )
      })}
      <div className="mx-3 mt-2 border-t border-white/10" />
    </section>
  )
}
