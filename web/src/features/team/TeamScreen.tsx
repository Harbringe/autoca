// Team & roles: who is in the firm, what each may do, who has been invited, and what changed lately.
//
// Everything offered comes from the server's own `can` flags. The owner sees the whole firm;
// administrators see and manage everyone except the owner; Senior CAs manage their own team.
// The server checks every change again.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { teamEvents, teamInvites, teamMembers, useRevokeInvite, useUpdateMember } from '@/api/queries/team'
import type { Invite, Member } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { tbl } from '@/components/ui/controls'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, formatDateTime, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { describeEvent } from '@/lib/team'
import { usePageTitle } from '@/lib/title'
import { useSession } from '@/session/session'
import { EditMemberDialog, InviteDialog } from './PeopleDialogs'

export function TeamScreen() {
  usePageTitle('Team & roles')
  const { can } = useSession()
  const members = useQuery({ ...teamMembers(), enabled: can('team.view') })
  const [inviting, setInviting] = useState(false)
  const [editing, setEditing] = useState<Member | null>(null)
  const [switching, setSwitching] = useState<Member | null>(null)
  const canInvite = members.data?.can.invite ?? false
  useHotkey('n', 'Invite a person', () => canInvite && setInviting(true), 'Team')

  if (!can('team.view')) return <EmptyState title="Not available">Team management is for firm administrators and Senior CAs.</EmptyState>
  if (members.isPending) return <Spinner label="Loading the team…" />
  if (members.error) return <ErrorState error={members.error} retry={() => void members.refetch()} />
  const info = members.data
  const rank = (role: string) => ({ FIRM_ADMIN: 0, SENIOR_CA: 1, STAFF: 2, READ_ONLY: 3 })[role as 'FIRM_ADMIN' | 'SENIOR_CA' | 'STAFF' | 'READ_ONLY'] ?? 4
  const rows = [...info.results].sort((a, b) => Number(b.is_active) - Number(a.is_active) || rank(a.role) - rank(b.role) || (a.manager?.name ?? '').localeCompare(b.manager?.name ?? '') || a.name.localeCompare(b.name))
  const active = rows.filter((m) => m.is_active).length

  return (
    <div className="grid gap-8 [&>*]:min-w-0">
      <div>
        <PageHeader
          title="Team & roles"
          description={
            info.can.manage
              ? `${plural(active, 'active person', 'active people')} in the firm. Reporting lines follow owner → administrator → Senior CA → staff.`
              : `${plural(active, 'active person', 'active people')} on your team, and you. Your team reports to you.`
          }
          actions={
            canInvite && (
              <Button onClick={() => setInviting(true)}>
                <Plus /> Invite a person
              </Button>
            )
          }
        />
        <div className={tbl.wrap}>
          <table className={tbl.table}>
            <caption className="sr-only">People in the firm</caption>
            <thead className={tbl.head}>
              <tr>
                <th scope="col" className={tbl.th}>Person</th>
                <th scope="col" className={tbl.th}>Role</th>
                <th scope="col" className={tbl.th}>Reports to</th>
                <th scope="col" className={tbl.th}>Clients</th>
                <th scope="col" className={tbl.th}>Last signed in</th>
                <th scope="col" className={tbl.th}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <MemberRow key={m.id} m={m} onEdit={() => setEditing(m)} onSwitch={() => setSwitching(m)} />
              ))}
            </tbody>
          </table>
        </div>
        {!info.can.manage && (
          <p className="mt-2 text-[13px] text-muted-foreground">
            You can change Staff and Read-only roles on your team, invite team members, and switch their access off and on. Administrators manage reporting lines and wider firm access.
          </p>
        )}
      </div>

      {canInvite && <Invites />}
      <History />

      <InviteDialog open={inviting} onOpenChange={setInviting} info={info} />
      <EditMemberDialog member={editing} info={info} onClose={() => setEditing(null)} />
      <SwitchAccess member={switching} onClose={() => setSwitching(null)} />
    </div>
  )
}

function MemberRow({ m, onEdit, onSwitch }: { m: Member; onEdit: () => void; onSwitch: () => void }) {
  const shown = m.clients.slice(0, 3)
  return (
    <tr className={`${tbl.row} ${m.is_active ? '' : 'text-muted-foreground'}`}>
      <td className={tbl.td}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">{m.name}</span>
          {m.is_me && <Badge>You</Badge>}
          {m.is_owner && <Badge tone="info">Owner</Badge>}
          {!m.is_active && <Badge tone="warning">Deactivated</Badge>}
        </div>
        <div className="text-[13px] text-muted-foreground">{m.email}</div>
      </td>
      <td className={`${tbl.td} whitespace-nowrap`}>
        {m.role_display}
        {m.scope_all_clients && m.role !== 'FIRM_ADMIN' && <div className="text-[13px] text-muted-foreground">Every client</div>}
      </td>
      <td className={tbl.td}>{m.manager?.name ?? <span className="text-muted-foreground">—</span>}</td>
      <td className={`${tbl.td} max-w-64`}>
        {m.role === 'FIRM_ADMIN' ? (
          <span className="text-muted-foreground">Every client</span>
        ) : shown.length ? (
          <span className="flex flex-wrap gap-x-2 text-[13px]">
            {shown.map((c) => (
              <Link key={c.id + c.how} to="/clients/$clientId" params={{ clientId: c.id }} className="hover:underline" title={c.how === 'leads' ? 'Senior CA of this client' : 'Assigned'}>
                {c.name}
                {c.how === 'leads' && <span className="text-muted-foreground"> (lead)</span>}
              </Link>
            ))}
            {m.clients.length > shown.length && (
              <span className="text-muted-foreground" title={m.clients.map((c) => c.name).join(', ')}>
                +{m.clients.length - shown.length} more
              </span>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">None</span>
        )}
      </td>
      <td className={`${tbl.td} num whitespace-nowrap text-muted-foreground`}>{m.last_login ? formatDateTime(m.last_login) : 'Never'}</td>
      <td className={`${tbl.td} whitespace-nowrap text-right`}>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/staff" search={{ member: m.id }}>
            Work
          </Link>
        </Button>
        {(m.can.manage || m.can.manage_role) && (
          <Button variant="ghost" size="sm" onClick={onEdit} aria-label={`Edit ${m.name}`}>
            Edit
          </Button>
        )}
        {m.can.set_active && (
          <Button variant="ghost" size="sm" onClick={onSwitch} aria-label={`${m.is_active ? 'Deactivate' : 'Reactivate'} ${m.name}`}>
            {m.is_active ? 'Deactivate' : 'Reactivate'}
          </Button>
        )}
      </td>
    </tr>
  )
}

/** People are never deleted (their work is on the books); switching access off is how they leave. */
function SwitchAccess({ member, onClose }: { member: Member | null; onClose: () => void }) {
  const update = useUpdateMember()
  const off = member?.is_active ?? true
  return (
    <Confirm
      open={!!member}
      onOpenChange={(o) => !o && onClose()}
      title={member ? `${off ? 'Deactivate' : 'Reactivate'} ${member.name}?` : ''}
      confirmLabel={off ? 'Deactivate' : 'Reactivate'}
      destructive={off}
      onConfirm={async () => {
        await update.mutateAsync({ id: member!.id, patch: { is_active: !off } })
        toast.success(`${member!.name} ${off ? 'deactivated' : 'reactivated'}`)
      }}
    >
      {off ? (
        <>
          <p>{member?.name} will not be able to sign in. Everything they did stays on the books, under their name.</p>
          <p>Anyone still leading a team or clients must hand them over first; the server will say so if that applies.</p>
        </>
      ) : (
        <p>{member?.name} will be able to sign in again, with the same role and team.</p>
      )}
    </Confirm>
  )
}

function Invites() {
  const invites = useQuery(teamInvites())
  const revoke = useRevokeInvite()
  const [target, setTarget] = useState<Invite | null>(null)
  return (
    <section aria-labelledby="pending-invites">
      <h2 id="pending-invites" className="mb-2 text-base font-semibold">
        Pending invitations
      </h2>
      {invites.isPending ? (
        <Spinner label="Loading invitations…" />
      ) : invites.error ? (
        <ErrorState error={invites.error} retry={() => void invites.refetch()} />
      ) : invites.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">No invitations waiting. People who have not yet accepted appear here for seven days.</p>
      ) : (
        <div className={tbl.wrap}>
          <table className={tbl.table}>
            <thead className={tbl.head}>
              <tr>
                <th scope="col" className={tbl.th}>Email</th>
                <th scope="col" className={tbl.th}>Role</th>
                <th scope="col" className={tbl.th}>Team of</th>
                <th scope="col" className={tbl.th}>Invited by</th>
                <th scope="col" className={tbl.th}>Expires</th>
                <th scope="col" className={tbl.th}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {invites.data.results.map((i) => (
                <tr key={i.id} className={tbl.row}>
                  <td className={tbl.td}>
                    <div className="font-medium">{i.email}</div>
                    {i.full_name && <div className="text-[13px] text-muted-foreground">{i.full_name}</div>}
                  </td>
                  <td className={tbl.td}>{i.role_display}</td>
                  <td className={tbl.td}>{i.manager?.name ?? <span className="text-muted-foreground">—</span>}</td>
                  <td className={`${tbl.td} text-muted-foreground`}>{i.created_by ?? '—'}</td>
                  <td className={`${tbl.td} num`}>{formatDate(i.expires_at)}</td>
                  <td className={`${tbl.td} text-right`}>
                    <Button variant="ghost" size="sm" onClick={() => setTarget(i)} aria-label={`Revoke the invitation to ${i.email}`}>
                      Revoke
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Confirm
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        title={target ? `Revoke the invitation to ${target.email}?` : ''}
        confirmLabel="Revoke invitation"
        destructive
        onConfirm={async () => {
          await revoke.mutateAsync(target!.id)
          toast.success('Invitation revoked')
        }}
      >
        <p>The link stops working at once. You can invite the same address again later.</p>
      </Confirm>
    </section>
  )
}

const HISTORY_STEP = 15

function History() {
  const events = useQuery(teamEvents())
  const [shown, setShown] = useState(HISTORY_STEP)
  const rows = events.data?.results ?? []
  return (
    <section aria-labelledby="team-history">
      <h2 id="team-history" className="mb-2 text-base font-semibold">
        Recent changes
      </h2>
      {events.isPending ? (
        <Spinner label="Loading history…" />
      ) : events.error ? (
        <ErrorState error={events.error} retry={() => void events.refetch()} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing has changed yet.</p>
      ) : (
        <>
          <ul className="divide-y rounded-lg border bg-card text-sm">
            {rows.slice(0, shown).map((e) => (
              <li key={e.id} className="flex flex-wrap items-baseline gap-x-3 px-4 py-2">
                <span className="num w-36 shrink-0 text-[13px] text-muted-foreground">{formatDateTime(e.at)}</span>
                <span>{describeEvent(e)}</span>
              </li>
            ))}
          </ul>
          {rows.length > shown && (
            <Button variant="ghost" size="sm" className="mt-2" onClick={() => setShown(shown + HISTORY_STEP)}>
              Show more
            </Button>
          )}
        </>
      )}
    </section>
  )
}
