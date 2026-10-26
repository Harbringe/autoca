// Team & roles: who is in the firm, what each may do, who has been invited, and what changed lately.
//
// Everything offered comes from the server's own `can` flags. The owner sees the whole firm;
// administrators see the whole firm, the owner included, but only the owner changes an administrator or the owner; Senior CAs manage their own team.
// The server checks every change again.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Plus, Users } from 'lucide-react'
import { useState } from 'react'
import { toast } from '@/lib/toast'
import { messageOf } from '@/api/errors'
import { teamEvents, teamInvites, teamMembers, useExtendInvite, useRegenerateInvite, useRevokeInvite, useUpdateMember, type InviteCreated } from '@/api/queries/team'
import type { Invite, Member } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable, type Column } from '@/components/ui/table'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, formatDateTime, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { describeEvent } from '@/lib/team'
import { usePageTitle } from '@/lib/title'
import { useSession } from '@/session/session'
import { BulkInviteDialog } from './BulkInviteDialog'
import { LinkBox } from './LinkBox'
import { EditMemberDialog, InviteDialog } from './PeopleDialogs'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

export function TeamScreen() {
  usePageTitle('Team & roles')
  const { can } = useSession()
  const members = useQuery({ ...teamMembers(), enabled: can('team.view') })
  const [inviting, setInviting] = useState(false)
  const [invitingMany, setInvitingMany] = useState(false)
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
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => setInvitingMany(true)}>
                  <Users /> Invite several
                </Button>
                <Button onClick={() => setInviting(true)}>
                  <Plus /> Invite a person
                </Button>
              </div>
            )
          }
        />
        <DataTable
          caption="People in the firm"
          columns={memberColumns(setEditing, setSwitching)}
          rows={rows}
          rowKey={(m) => m.id}
          rowClassName={(m) => (m.is_active ? undefined : 'text-muted-foreground')}
        />
        {!info.can.manage && (
          <p className="mt-2 text-[13px] text-muted-foreground">
            You can change Staff and Read-only roles on your team, invite team members, and switch their access off and on. Administrators manage reporting lines and wider firm access.
          </p>
        )}
      </div>

      {canInvite && <Invites />}
      <History />

      <InviteDialog open={inviting} onOpenChange={setInviting} info={info} />
      <BulkInviteDialog open={invitingMany} onOpenChange={setInvitingMany} info={info} />
      <EditMemberDialog member={editing} info={info} onClose={() => setEditing(null)} />
      <SwitchAccess member={switching} onClose={() => setSwitching(null)} />
    </div>
  )
}

function memberColumns(onEdit: (m: Member) => void, onSwitch: (m: Member) => void): Column<Member>[] {
  return [
    {
      key: 'person',
      header: 'Person',
      cell: (m) => (
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium text-heading">{m.name}</span>
            {m.is_me && <Badge>You</Badge>}
            {m.is_owner && <Badge tone="info">Owner</Badge>}
            {!m.is_active && <Badge tone="attention">Deactivated</Badge>}
          </div>
          <div className="text-[13px] text-muted-foreground">{m.email}</div>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      cell: (m) => (
        <div className="whitespace-nowrap">
          {m.role_display}
          {m.scope_all_clients && m.role !== 'FIRM_ADMIN' && <div className="text-[13px] text-muted-foreground">Every client</div>}
        </div>
      ),
    },
    { key: 'manager', header: 'Reports to', priority: 2, cell: (m) => m.manager?.name ?? <span className="text-muted-foreground">—</span> },
    { key: 'clients', header: 'Clients', priority: 3, cell: (m) => <ClientsCell m={m} /> },
    {
      key: 'login',
      header: 'Last signed in',
      priority: 3,
      cell: (m) => <span className="num whitespace-nowrap text-muted-foreground">{m.last_login ? formatDateTime(m.last_login) : 'Never'}</span>,
    },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (m) => (
        <div className="whitespace-nowrap">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/staff" search={{ member: m.id }} aria-label={`See ${m.name}’s work`}>
              Work
            </Link>
          </Button>
          {!m.can.manage && !m.can.manage_role && !m.can.set_active && m.role === 'FIRM_ADMIN' && (
            <span className="ml-1 text-xs text-muted-foreground">{m.is_owner ? 'Changed by handing over ownership' : 'Only the owner can change this'}</span>
          )}
          {(m.can.manage || m.can.manage_role) && (
            <Button variant="ghost" size="sm" onClick={() => onEdit(m)} aria-label={`Edit ${m.name}`}>
              Edit
            </Button>
          )}
          {m.can.set_active && (
            <Button variant="ghost" size="sm" onClick={() => onSwitch(m)} aria-label={`${m.is_active ? 'Deactivate' : 'Reactivate'} ${m.name}`}>
              {m.is_active ? 'Deactivate' : 'Reactivate'}
            </Button>
          )}
        </div>
      ),
    },
  ]
}

function ClientsCell({ m }: { m: Member }) {
  const shown = m.clients.slice(0, 3)
  if (m.role === 'FIRM_ADMIN') return <span className="text-muted-foreground">Every client</span>
  if (!shown.length) return <span className="text-muted-foreground">None</span>
  return (
    <span className="flex max-w-64 flex-wrap gap-x-2 text-[13px]">
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
  const regenerate = useRegenerateInvite()
  const extend = useExtendInvite()
  const [target, setTarget] = useState<Invite | null>(null)
  const [fresh, setFresh] = useState<InviteCreated | null>(null)

  async function newLink(i: Invite) {
    try {
      setFresh(await regenerate.mutateAsync(i.id))
    } catch (e) {
      toast.error(messageOf(e))
    }
  }
  async function moreTime(i: Invite) {
    try {
      const updated = await extend.mutateAsync(i.id)
      toast.success(`${i.email} has until ${formatDate(updated.expires_at)}`)
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  return (
    <section aria-labelledby="pending-invites">
      <h3 id="pending-invites" className="mb-2 text-[15px] font-semibold text-heading">
        Pending invitations
      </h3>
      {invites.isPending ? (
        <Spinner label="Loading invitations…" />
      ) : invites.error ? (
        <ErrorState error={invites.error} retry={() => void invites.refetch()} />
      ) : invites.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">No invitations waiting. People who have not yet accepted appear here, and an expired invitation stays for a month so it can be sent again.</p>
      ) : (
        <DataTable
          caption="Pending invitations"
          columns={inviteColumns({ onRevoke: setTarget, onNewLink: (i) => void newLink(i), onExtend: (i) => void moreTime(i), busy: regenerate.isPending || extend.isPending })}
          rows={invites.data.results}
          rowKey={(i) => i.id}
        />
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
      <Dialog open={!!fresh} onOpenChange={(o) => !o && setFresh(null)}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>A new link for {fresh?.email}</DialogTitle>
            <DialogDescription>
              The old link no longer works. Send this one; it works once and expires on {fresh ? formatDate(fresh.expires_at) : ''}. It is shown only now.
            </DialogDescription>
          </DialogHeader>
          {fresh && <LinkBox link={fresh.link} />}
          <DialogFooter>
            <Button autoFocus onClick={() => setFresh(null)}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

const STATUS: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'info' }> = {
  pending: { label: 'Waiting', tone: 'info' },
  expiring_soon: { label: 'Expires soon', tone: 'warning' },
  expired: { label: 'Expired', tone: 'danger' },
}

function inviteColumns({
  onRevoke,
  onNewLink,
  onExtend,
  busy,
}: {
  onRevoke: (i: Invite) => void
  onNewLink: (i: Invite) => void
  onExtend: (i: Invite) => void
  busy: boolean
}): Column<Invite>[] {
  return [
    {
      key: 'email',
      header: 'Email',
      cell: (i) => (
        <div>
          <div className="font-medium text-heading">{i.email}</div>
          {i.full_name && <div className="text-[13px] text-muted-foreground">{i.full_name}</div>}
        </div>
      ),
    },
    { key: 'role', header: 'Role', cell: (i) => i.role_display },
    { key: 'manager', header: 'Team of', priority: 2, cell: (i) => i.manager?.name ?? <span className="text-muted-foreground">—</span> },
    { key: 'by', header: 'Invited by', priority: 3, cell: (i) => <span className="text-muted-foreground">{i.created_by ?? '—'}</span> },
    {
      key: 'status',
      header: 'Status',
      cell: (i) => {
        const s = STATUS[i.status] ?? STATUS.pending!
        return <Badge tone={s.tone}>{s.label}</Badge>
      },
    },
    { key: 'expires', header: 'Expires', priority: 2, cell: (i) => <span className="num">{formatDate(i.expires_at)}</span> },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (i) => (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => onNewLink(i)} aria-label={`Make a new link for ${i.email}`}>
            New link
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => onExtend(i)} aria-label={`Give ${i.email} another week`}>
            +7 days
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onRevoke(i)} aria-label={`Revoke the invitation to ${i.email}`}>
            Revoke
          </Button>
        </div>
      ),
    },
  ]
}

const HISTORY_STEP = 15

function History() {
  const events = useQuery(teamEvents())
  const [shown, setShown] = useState(HISTORY_STEP)
  const rows = events.data?.results ?? []
  return (
    <section aria-labelledby="team-history">
      <h3 id="team-history" className="mb-2 text-[15px] font-semibold text-heading">
        Recent changes
      </h3>
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
