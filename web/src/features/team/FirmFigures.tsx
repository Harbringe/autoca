// The firm's four figures (people, Senior CAs, staff, clients), each a button that opens the list behind the number, paged. The people come
// from the team's list and the clients from the team's client list, both of which a firm administrator is allowed to see.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { teamClients, teamMembers } from '@/api/queries/team'
import type { Role } from '@/api/types'
import { PagedList } from '@/components/ca/Pager'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'
import { initialsOf } from '@/lib/useDebounced'

export type Figure = 'people' | 'senior' | 'staff' | 'clients'

export const FIGURES: { id: Figure; label: string; title: string }[] = [
  { id: 'people', label: 'People', title: 'People who can sign in' },
  { id: 'senior', label: 'Senior CAs', title: 'Senior CAs' },
  { id: 'staff', label: 'Staff', title: 'Staff and read-only' },
  { id: 'clients', label: 'Clients', title: 'Clients' },
]

const inFigure = (figure: Figure, role: Role) => (figure === 'people' ? true : figure === 'senior' ? role === 'SENIOR_CA' : role === 'STAFF' || role === 'READ_ONLY')

function Tile({ name }: { name: string }) {
  return (
    <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-md border bg-muted text-[11px] font-bold">
      {initialsOf(name).slice(0, 2)}
    </span>
  )
}

function People({ figure }: { figure: Exclude<Figure, 'clients'> }) {
  const members = useQuery(teamMembers())
  if (members.isPending) return <Spinner label="Loading people…" />
  if (members.error)
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load the people.
      </p>
    )
  const rows = members.data.results.filter((m) => m.is_active && inFigure(figure, m.role))
  if (!rows.length) return <p className="py-6 text-center text-sm text-muted-foreground">Nobody here yet.</p>
  return (
    <PagedList rows={rows} resetKey={figure} label="People" section="firm">
      {(shown) => (
        <ul className="divide-y rounded-lg border">
          {shown.map((m) => (
            <li key={m.id} className="flex items-center gap-3 px-4 py-3 text-sm">
              <Tile name={m.name} />
              <span className="min-w-0 flex-1">
                <b className="block truncate font-medium text-heading">{m.name}</b>
                <span className="block truncate text-[13px] text-muted-foreground">{m.email}</span>
              </span>
              <Badge tone={m.is_owner ? 'info' : 'neutral'}>{m.is_owner ? 'Owner' : m.role_display}</Badge>
              <span className="num hidden w-28 shrink-0 text-right text-[13px] text-muted-foreground sm:block">{m.last_login ? formatDate(m.last_login) : 'Not yet'}</span>
            </li>
          ))}
        </ul>
      )}
    </PagedList>
  )
}

function Clients() {
  const clients = useQuery(teamClients())
  if (clients.isPending) return <Spinner label="Loading clients…" />
  if (clients.error)
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load the clients.
      </p>
    )
  const rows = clients.data.results
  if (!rows.length) return <p className="py-6 text-center text-sm text-muted-foreground">No clients yet.</p>
  return (
    <PagedList rows={rows} resetKey="clients" label="Clients" section="firm">
      {(shown) => (
        <ul className="divide-y rounded-lg border">
          {shown.map((c) => (
            <li key={c.id}>
              <Link to="/clients/$clientId" params={{ clientId: c.id }} className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-hover">
                <Tile name={c.name} />
                <b className="min-w-0 flex-1 truncate font-medium text-heading">{c.name}</b>
                <span className="text-[13px] text-muted-foreground">{c.lead ? `Lead: ${c.lead.name}` : 'No lead yet'}</span>
                <span className="num hidden text-[13px] text-muted-foreground sm:block">{plural(c.unresolved, 'row')} to place</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PagedList>
  )
}

/** The list behind one of the firm's figures, in a dialog. */
export function FigureDialog({ figure, onClose }: { figure: Figure | null; onClose: () => void }) {
  const meta = FIGURES.find((f) => f.id === figure)
  return (
    <Dialog open={!!figure} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl" aria-describedby="figure-help">
        <DialogHeader>
          <DialogTitle>{meta?.title}</DialogTitle>
          <DialogDescription id="figure-help">
            {figure === 'clients' ? 'Every client of the firm, with who leads it.' : 'Active people in the firm. Roles and invitations are managed on the Team page.'}
          </DialogDescription>
        </DialogHeader>
        {figure === 'clients' ? <Clients /> : figure ? <People figure={figure} /> : null}
        {figure && figure !== 'clients' && (
          <p className="text-[13px]">
            <Link to="/settings/team" className="text-link underline underline-offset-2" onClick={onClose}>
              Open the Team page
            </Link>
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
