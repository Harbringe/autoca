// The Team page: people, clients, work and history. For firm admins (the whole
// firm) and Senior CAs (their own team and the clients they lead). Every rule
// shown here is enforced again by the server; hidden controls are a courtesy.

import { useState, type FormEvent } from 'react'
import { Link, NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useSession } from '../../auth/session'
import { Badge, Button, Empty, ErrorNote, Field, formatDate, formatDateTime, Modal, Note, Spinner, useAsync } from '../../components/ui'
import { ROLE_LABELS, teamApi, type Member, type MembersPage, type Person, type TeamClient } from './api'
import WorkPanel, { RangePicker, rangeFor } from './WorkPanel'

export default function Team() {
  const { me } = useSession()
  const isAdmin = me?.role === 'FIRM_ADMIN'
  const { pathname } = useLocation()
  const onPerson = pathname.startsWith('/team/people/')
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{isAdmin ? 'Team' : 'My team'}</h1>
          <p className="sub">
            {isAdmin
              ? 'Who is in the firm, who leads which clients, and who is working on what.'
              : 'The people on your team, the clients you lead, and the work getting done.'}
          </p>
        </div>
      </div>
      <nav className="tabs">
        <NavLink to="/team" end className={({ isActive }) => (isActive || onPerson ? 'active' : '')}>
          People
        </NavLink>
        <NavLink to="/team/clients">Clients</NavLink>
        <NavLink to="/team/work">Work</NavLink>
        <NavLink to="/team/history">History</NavLink>
      </nav>
      <Routes>
        <Route index element={<People />} />
        <Route path="people/:memberId" element={<PersonPage />} />
        <Route path="clients" element={<Clients />} />
        <Route path="work" element={<Work />} />
        <Route path="history" element={<History />} />
      </Routes>
    </>
  )
}

function StatusBadge({ person }: { person: { is_active: boolean } }) {
  return person.is_active ? <Badge tone="good">Active</Badge> : <Badge tone="bad">Deactivated</Badge>
}

// ---------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------

function People() {
  const { data, error, loading, reload } = useAsync(() => teamApi.members(rangeFor('month')), [])
  const [inviting, setInviting] = useState(false)
  const [editing, setEditing] = useState<Member | null>(null)
  const [invitesVersion, setInvitesVersion] = useState(0)

  if (loading && !data) return <Spinner />
  if (!data) return <ErrorNote error={error} />

  const leads = data.results.filter((m) => m.role === 'SENIOR_CA' || m.role === 'FIRM_ADMIN')
  const groups = leads
    .map((lead) => ({ lead, members: data.results.filter((m) => m.manager?.id === lead.id) }))
    .filter((g) => data.can.manage || g.members.length || g.lead.is_me)
  const unplaced = data.results.filter(
    (m) => !m.manager && m.role !== 'SENIOR_CA' && m.role !== 'FIRM_ADMIN',
  )

  return (
    <>
      <div className="row between" style={{ marginBottom: 12 }}>
        <span className="sub">
          {data.results.filter((m) => m.is_active).length} active · work shown for the last 30 days
        </span>
        <div className="row">
          <Button kind="primary" onClick={() => setInviting(true)}>
            Invite someone
          </Button>
        </div>
      </div>

      <PendingInvites key={invitesVersion} />

      {groups.map(({ lead, members }) => (
        <div className="panel" key={lead.id}>
          <div className="panel-head">
            <div>
              <h2>
                <Link to={`/team/people/${lead.id}`}>{lead.name}</Link>{' '}
                <Badge tone="info">{lead.role_display}</Badge> {!lead.is_active && <StatusBadge person={lead} />}
              </h2>
              <span className="sub">
                Leads {lead.clients.filter((c) => c.how === 'leads').length} client(s) · {members.length} on team
                {lead.work.entries_approved ? ` · approved ${lead.work.entries_approved} entries in 30 days` : ''}
              </span>
            </div>
            {lead.can.manage && (
              <Button className="btn-sm" onClick={() => setEditing(lead)}>
                Edit
              </Button>
            )}
          </div>
          <MemberTable members={members} metrics={data.metrics} onEdit={setEditing} empty="Nobody on this team yet." />
        </div>
      ))}

      {unplaced.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <div>
              <h2>Not on a team</h2>
              <span className="sub">Put these people under a Senior CA so someone is looking after their work.</span>
            </div>
          </div>
          <MemberTable members={unplaced} metrics={data.metrics} onEdit={setEditing} empty="" />
        </div>
      )}

      {inviting && (
        <InviteDialog
          page={data}
          onClose={() => setInviting(false)}
          onDone={() => {
            reload()
            setInvitesVersion((v) => v + 1)
          }}
        />
      )}
      {editing && (
        <EditMember
          member={editing}
          page={data}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            reload()
          }}
        />
      )}
    </>
  )
}

function MemberTable({
  members,
  metrics,
  onEdit,
  empty,
}: {
  members: Member[]
  metrics: MembersPage['metrics']
  onEdit: (m: Member) => void
  empty: string
}) {
  if (!members.length) return <div className="panel-body sub">{empty}</div>
  const keys = ['rows_placed', 'statements_uploaded', 'entries_approved']
  const shown = metrics.filter((m) => keys.includes(m.key))
  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th>Person</th>
            <th>Role</th>
            <th>Clients</th>
            {shown.map((m) => (
              <th key={m.key} className="num">
                {m.label}
              </th>
            ))}
            <th>Last sign-in</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.id} style={{ opacity: m.is_active ? 1 : 0.55 }}>
              <td>
                <Link to={`/team/people/${m.id}`}>
                  <strong>{m.name}</strong>
                </Link>
                {m.full_name && <div className="sub">{m.email}</div>}
              </td>
              <td>
                {m.role_display} {!m.is_active && <StatusBadge person={m} />}
              </td>
              <td>
                {m.scope_all_clients ? (
                  <Badge>All clients</Badge>
                ) : m.clients.length ? (
                  <span title={m.clients.map((c) => c.name).join(', ')}>{m.clients.length}</span>
                ) : (
                  <Badge tone="warn">None</Badge>
                )}
              </td>
              {shown.map((metric) => (
                <td key={metric.key} className="num">
                  {m.work[metric.key] || ''}
                </td>
              ))}
              <td>{m.last_login ? formatDateTime(m.last_login) : 'Never'}</td>
              <td className="num">
                {(m.can.manage || m.can.set_active) && (
                  <Button className="btn-sm" onClick={() => onEdit(m)}>
                    Edit
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PendingInvites() {
  const { data, reload } = useAsync(() => teamApi.invites(), [])
  const [error, setError] = useState<unknown>(null)
  if (!data?.results.length) return null
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Invites waiting to be accepted</h2>
      </div>
      <ErrorNote error={error} />
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Team</th>
              <th>Expires</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((invite) => (
              <tr key={invite.id}>
                <td>{invite.email}</td>
                <td>{invite.role_display}</td>
                <td>{invite.manager?.name ?? '—'}</td>
                <td>{formatDate(invite.expires_at)}</td>
                <td className="num">
                  <Button
                    className="btn-sm"
                    onClick={() => {
                      setError(null)
                      teamApi.revokeInvite(invite.id).then(reload, setError)
                    }}
                  >
                    Revoke
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function InviteDialog({ page, onClose, onDone }: { page: MembersPage; onClose: () => void; onDone: () => void }) {
  const { me } = useSession()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState('STAFF')
  const [manager, setManager] = useState<string>(page.can.manage ? '' : me?.membership_id ?? '')
  const [link, setLink] = useState('')
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const teamRole = role === 'STAFF' || role === 'READ_ONLY'

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await teamApi.invite({
        email: email.trim(),
        full_name: name.trim(),
        role,
        manager: teamRole && manager ? manager : null,
      })
      setLink(`${window.location.origin}${result.link}`)
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (link) {
    return (
      <Modal title="Invite ready" onClose={onClose}>
        <div className="stack">
          <p>
            Send this link to <strong>{email}</strong> however you normally would. It works once and expires in 7 days. They
            choose a password and set up their authenticator when they open it.
          </p>
          <input type="text" readOnly value={link} onFocus={(e) => e.target.select()} />
          <Note tone="warn">This is the only time the link is shown. If it's lost, send a new invite.</Note>
          <div className="row end">
            <Button
              kind="primary"
              onClick={() => {
                void navigator.clipboard?.writeText(link).then(() => setCopied(true))
              }}
            >
              {copied ? 'Copied' : 'Copy link'}
            </Button>
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title="Invite someone" onClose={onClose}>
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Email">
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </Field>
        <Field label="Name" hint="Optional. They can change it when they accept.">
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Role">
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {page.can.invite_roles.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
        </Field>
        {teamRole &&
          (page.can.manage ? (
            <Field label="Team" hint="The Senior CA who will look after their work.">
              <select value={manager} onChange={(e) => setManager(e.target.value)}>
                <option value="">Not on a team yet</option>
                {page.leads.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name} ({l.role_display})
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <p className="sub">They'll join your team. You can then put them on the clients you lead.</p>
          ))}
        <p className="sub">
          {teamRole
            ? 'They will only see the clients they are assigned to.'
            : 'Senior CAs see the clients they lead; firm administrators see everything.'}
        </p>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Create invite link
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function EditMember({
  member,
  page,
  onClose,
  onSaved,
}: {
  member: Member
  page: MembersPage
  onClose: () => void
  onSaved: () => void
}) {
  const [role, setRole] = useState(member.role)
  const [manager, setManager] = useState(member.manager?.id ?? '')
  const [keep, setKeep] = useState(false)
  const [allClients, setAllClients] = useState(member.scope_all_clients)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const teamRole = role === 'STAFF' || role === 'READ_ONLY'
  const movingTeams = teamRole && (member.manager?.id ?? '') !== manager
  const leadsClientsWithOldManager = member.clients.filter((c) => c.how === 'assigned').length

  async function save(body: Record<string, unknown>) {
    setBusy(true)
    setError(null)
    try {
      await teamApi.update(member.id, body)
      onSaved()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const body: Record<string, unknown> = {}
    if (role !== member.role) body.role = role
    if (movingTeams) {
      body.manager = manager || null
      body.keep_client_assignments = keep
    }
    if (member.role !== 'FIRM_ADMIN' && allClients !== member.scope_all_clients) body.scope_all_clients = allClients
    if (!Object.keys(body).length) return onClose()
    void save(body)
  }

  return (
    <Modal title={member.name} onClose={onClose}>
      <ErrorNote error={error} />
      {member.can.manage ? (
        <form onSubmit={submit}>
          <Field label="Role">
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {Object.entries(ROLE_LABELS)
                .filter(([value]) => value !== 'FIRM_ADMIN' || page.can.manage_admins || member.role === 'FIRM_ADMIN')
                .map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          {teamRole && (
            <Field label="Team">
              <select value={manager} onChange={(e) => setManager(e.target.value)}>
                <option value="">Not on a team</option>
                {page.leads
                  .filter((l) => l.id !== member.id)
                  .map((l: Person) => (
                    <option key={l.id} value={l.id}>
                      {l.name} ({l.role_display})
                    </option>
                  ))}
              </select>
            </Field>
          )}
          {movingTeams && member.manager && leadsClientsWithOldManager > 0 && (
            <label className="row" style={{ marginBottom: 12 }}>
              <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
              <span>
                Keep them on {member.manager.name}'s clients. Otherwise they come off those clients when they change team.
              </span>
            </label>
          )}
          {member.role !== 'FIRM_ADMIN' && (
            <label className="row" style={{ marginBottom: 12 }}>
              <input type="checkbox" checked={allClients} onChange={(e) => setAllClients(e.target.checked)} />
              <span>Can see every client in the firm (for example an internal auditor)</span>
            </label>
          )}
          <div className="row between">
            <ActiveToggle member={member} busy={busy} onToggle={(active) => void save({ is_active: active })} />
            <div className="row">
              <Button onClick={onClose}>Cancel</Button>
              <Button kind="primary" type="submit" busy={busy}>
                Save
              </Button>
            </div>
          </div>
        </form>
      ) : (
        <div className="stack">
          <p>
            {member.role_display} on your team. {member.is_active ? 'They can sign in.' : 'Their access is switched off.'}
          </p>
          <div className="row between">
            <ActiveToggle member={member} busy={busy} onToggle={(active) => void save({ is_active: active })} />
            <Button onClick={onClose}>Close</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function ActiveToggle({ member, busy, onToggle }: { member: Member; busy: boolean; onToggle: (active: boolean) => void }) {
  const [confirming, setConfirming] = useState(false)
  if (!member.can.set_active) return <span />
  if (!member.is_active) {
    return (
      <Button busy={busy} onClick={() => onToggle(true)}>
        Reactivate
      </Button>
    )
  }
  return confirming ? (
    <span className="row">
      <span className="sub">They'll be signed out of this firm.</span>
      <Button kind="danger" busy={busy} onClick={() => onToggle(false)}>
        Deactivate
      </Button>
    </span>
  ) : (
    <Button kind="ghost" onClick={() => setConfirming(true)}>
      Deactivate…
    </Button>
  )
}

// ---------------------------------------------------------------------------
// One person
// ---------------------------------------------------------------------------

function PersonPage() {
  const { memberId = '' } = useParams()
  const [rangeKey, setRangeKey] = useState('month')
  return (
    <>
      <div className="row between" style={{ marginBottom: 12 }}>
        <Link to="/team">← Team</Link>
        <RangePicker value={rangeKey} onChange={setRangeKey} />
      </div>
      <PersonHeader memberId={memberId} />
      <WorkPanel memberId={memberId} rangeKey={rangeKey} />
    </>
  )
}

function PersonHeader({ memberId }: { memberId: string }) {
  const { data } = useAsync(() => teamApi.members(rangeFor('month')), [memberId])
  const member = data?.results.find((m) => m.id === memberId)
  if (!member) return null
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-body row between">
        <div>
          <h2 style={{ margin: 0 }}>{member.name}</h2>
          <div className="sub">
            {member.role_display}
            {member.manager ? ` · on ${member.manager.name}'s team` : ''} · {member.email}
          </div>
        </div>
        <div className="row">
          <StatusBadge person={member} />
          {member.scope_all_clients && <Badge>All clients</Badge>}
          {member.clients.map((c) => (
              <Badge key={c.id} tone={c.how === 'leads' ? 'info' : 'neutral'}>
                {c.how === 'leads' ? 'Leads ' : ''}
                {c.name}
              </Badge>
            ))}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Clients
// ---------------------------------------------------------------------------

function Clients() {
  const { data, error, loading, reload } = useAsync(() => teamApi.clients(), [])
  const { data: people } = useAsync(() => teamApi.members(rangeFor('week')), [])
  const [actionError, setActionError] = useState<unknown>(null)
  const [filter, setFilter] = useState('')

  if (loading && !data) return <Spinner />
  if (!data) return <ErrorNote error={error} />

  const run = (promise: Promise<unknown>) => {
    setActionError(null)
    promise.then(reload, setActionError)
  }
  const needle = filter.trim().toLowerCase()
  const clients = data.results.filter((c) => !needle || c.name.toLowerCase().includes(needle))
  const noLead = data.results.filter((c) => !c.lead).length

  return (
    <>
      <div className="row between" style={{ marginBottom: 12 }}>
        <input type="search" placeholder="Search clients" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {data.can.set_lead && noLead > 0 && (
          <Note tone="warn">
            {noLead} client{noLead === 1 ? ' has' : 's have'} no lead. Until one is set, any Senior CA who can see it may approve its
            entries.
          </Note>
        )}
      </div>
      <ErrorNote error={actionError} />
      <div className="panel">
        {!clients.length ? (
          <Empty title={data.can.set_lead ? 'No clients' : 'You don’t lead any clients yet'}>
            {data.can.set_lead ? undefined : 'A firm administrator makes you the lead of a client.'}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Lead</th>
                  <th>Working on it</th>
                  <th className="num">To place</th>
                  <th className="num">Awaiting approval</th>
                </tr>
              </thead>
              <tbody>
                {clients.map((client) => (
                  <ClientRow
                    key={client.id}
                    client={client}
                    canSetLead={data.can.set_lead}
                    leads={people?.leads ?? []}
                    assignable={data.assignable}
                    run={run}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}

function ClientRow({
  client,
  canSetLead,
  leads,
  assignable,
  run,
}: {
  client: TeamClient
  canSetLead: boolean
  leads: Person[]
  assignable: Person[]
  run: (p: Promise<unknown>) => void
}) {
  const available = assignable.filter((p) => p.id !== client.lead?.id && !client.team.some((t) => t.id === p.id))
  return (
    <tr>
      <td>
        <Link to={`/clients/${client.id}`}>
          <strong>{client.name}</strong>
        </Link>
      </td>
      <td>
        {canSetLead ? (
          <select value={client.lead?.id ?? ''} onChange={(e) => run(teamApi.setLead(client.id, e.target.value || null))}>
            <option value="">No lead</option>
            {leads.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        ) : (
          client.lead?.name ?? '—'
        )}
      </td>
      <td>
        <div className="row" style={{ gap: 6 }}>
          {client.team.map((person) => (
            <span key={person.id} className="chip" title={person.role_display}>
              {person.name}
              {!person.is_active && ' (off)'}
              {(canSetLead || person.on_my_team) && (
                <button type="button" aria-label={`Remove ${person.name}`} onClick={() => run(teamApi.unassign(client.id, person.id))}>
                  ×
                </button>
              )}
            </span>
          ))}
          {available.length > 0 && (
            <select
              value=""
              onChange={(e) => e.target.value && run(teamApi.assign(client.id, e.target.value))}
              aria-label={`Add someone to ${client.name}`}
            >
              <option value="">+ Add…</option>
              {available.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.role_display})
                </option>
              ))}
            </select>
          )}
          {!client.team.length && !available.length && <span className="sub">Nobody yet</span>}
        </div>
      </td>
      <td className="num">{client.unresolved}</td>
      <td className="num">{client.pending_approval}</td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Work
// ---------------------------------------------------------------------------

function Work() {
  const [rangeKey, setRangeKey] = useState('month')
  const { data, error, loading } = useAsync(() => teamApi.members(rangeFor(rangeKey)), [rangeKey])
  const navigate = useNavigate()

  return (
    <>
      <div className="row between" style={{ marginBottom: 12 }}>
        <span className="sub">Click a person for their day-by-day and per-client breakdown.</span>
        <RangePicker value={rangeKey} onChange={setRangeKey} />
      </div>
      <ErrorNote error={error} />
      <div className="panel">
        {loading || !data ? (
          <Spinner />
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Team</th>
                  {data.metrics.map((m) => (
                    <th key={m.key} className="num">
                      {m.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.results
                  .filter((m) => m.is_active || Object.values(m.work).some(Boolean))
                  .map((m) => (
                    <tr key={m.id} onClick={() => navigate(`/team/people/${m.id}`)} style={{ cursor: 'pointer' }}>
                      <td>
                        <strong>{m.name}</strong>
                        <div className="sub">{m.role_display}</div>
                      </td>
                      <td>{m.manager?.name ?? (m.role === 'STAFF' || m.role === 'READ_ONLY' ? '—' : 'Lead')}</td>
                      {data.metrics.map((metric) => (
                        <td key={metric.key} className="num">
                          {m.work[metric.key] || ''}
                        </td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

function describe(e: { kind: string; kind_display: string; detail: Record<string, string | number> }): string {
  const d = e.detail
  switch (e.kind) {
    case 'member.invited':
      return `invited ${d.email} as ${d.role}${d.to ? ` to ${d.to}'s team` : ''}`
    case 'member.joined':
      return `joined as ${d.role}`
    case 'invite.revoked':
      return `revoked the invite for ${d.email}`
    case 'member.role_changed':
      return `changed ${d.member}'s role from ${d.from} to ${d.to}`
    case 'member.manager_changed': {
      const removed = Number(d.removed_from_clients) ? ` (taken off ${d.removed_from_clients} client(s))` : ''
      if (d.from === 'nobody') return `put ${d.member} on ${d.to}'s team`
      if (d.to === 'nobody') return `took ${d.member} off ${d.from}'s team${removed}`
      return `moved ${d.member} from ${d.from}'s team to ${d.to}'s${removed}`
    }
    case 'member.scope_changed':
      return `turned all-clients access ${d.to} for ${d.member}`
    case 'member.deactivated':
      return `deactivated ${d.member}`
    case 'member.reactivated':
      return `reactivated ${d.member}`
    case 'client.lead_changed':
      if (d.from === 'nobody') return `made ${d.to} the lead of ${d.client}`
      if (d.to === 'nobody') return `removed ${d.from} as lead of ${d.client}`
      return `changed ${d.client}'s lead from ${d.from} to ${d.to}`
    case 'firm.owner_changed':
      return d.from === 'nobody' ? `made ${d.to} the firm owner` : `transferred ownership from ${d.from} to ${d.to}`
    case 'firm.renamed':
      return `renamed the firm from ${d.from} to ${d.to}`
    case 'client.assigned':
      return `put ${d.member} on ${d.client}`
    case 'client.unassigned':
      return `took ${d.member} off ${d.client}`
    default:
      return e.kind_display
  }
}

function History() {
  const { data, error, loading } = useAsync(() => teamApi.events(), [])
  if (loading && !data) return <Spinner />
  if (!data) return <ErrorNote error={error} />
  return (
    <div className="panel">
      {!data.results.length ? (
        <Empty title="No changes yet">Invites, team moves and client assignments will be listed here.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <tbody>
              {data.results.map((e) => (
                <tr key={e.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatDateTime(e.at)}</td>
                  <td>
                    <strong>{e.detail.actor}</strong> {describe(e)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
