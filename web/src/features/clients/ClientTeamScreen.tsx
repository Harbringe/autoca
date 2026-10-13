// A client's people and details: who leads it, who works on it, and its name, description and
// financial year. Everything offered follows the caller's permissions; the server checks again.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from '@/lib/toast'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { clientDetail, useUpdateClient, V1 } from '@/api/queries/clients'
import { teamClients, teamMembers, useAssign, useSetLead, useUnassign } from '@/api/queries/team'
import type { Client, Page } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Listbox } from '@/components/ui/listbox'
import { Select, Textarea } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, parseDate } from '@/lib/format'
import { useSession } from '@/session/session'
import { initials } from './clientsView'
import { ProfileHeader, ProfileSections } from './ProfileSections'

export function ClientTeamScreen({ clientId, justCreated }: { clientId: string; justCreated: boolean }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  if (client.isPending) return <Spinner label="Loading…" />
  if (client.error) return <ErrorState error={client.error} retry={() => void client.refetch()} />
  return (
    <div className="grid max-w-4xl gap-5">
      <ProfileHeader clientId={clientId} />
      {can('team.view') && <TeamRows clientId={clientId} justCreated={justCreated} />}
      <ProfileSections clientId={clientId} />
      {can('client.update') && <DetailsRows client={client.data} />}
    </div>
  )
}

/** `split` is the roomy form used on the pipeline page: one card, the lead on the left and the team on the right. */
export function People({ clientId, justCreated, split = false }: { clientId: string; justCreated: boolean; split?: boolean }) {
  const clients = useQuery(teamClients())
  const members = useQuery(teamMembers())
  const setLead = useSetLead()
  const assign = useAssign()
  const unassign = useUnassign()
  const [pick, setPick] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [removing, setRemoving] = useState<{ id: string; name: string } | null>(null)
  const leadRef = useRef<HTMLSelectElement>(null)

  const row = clients.data?.results.find((c) => c.id === clientId)
  const canSetLead = clients.data?.can.set_lead ?? false
  const needsLead = justCreated && !!row && !row.lead && canSetLead
  useEffect(() => {
    if (needsLead) leadRef.current?.focus()
  }, [needsLead])

  if (clients.isPending || members.isPending) return <Spinner label="Loading the team…" />
  if (clients.error) return <ErrorState error={clients.error} retry={() => void clients.refetch()} />
  if (!row) return <p className="text-sm text-muted-foreground">You do not manage this client’s team.</p>

  const leads = members.data?.leads ?? []
  const assigned = new Set(row.team.map((p) => p.id))
  const addable = clients.data.assignable.filter((p) => !assigned.has(p.id))

  async function run(action: () => Promise<unknown>, done: string) {
    setError(null)
    try {
      await action()
      toast.success(done)
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <section aria-labelledby="ct-people" className={split ? 'grid gap-6 rounded-xl border border-border-strong bg-surface-2 p-6' : 'grid gap-5 rounded-lg border bg-card p-5'}>
      <h2 id="ct-people" className={split ? 'sr-only' : 'text-[15px] font-semibold text-heading'}>
        Senior CA and team
      </h2>
      {needsLead && (
        <p role="status" className="rounded-md border border-info/30 bg-info-bg px-4 py-2.5 text-sm">
          This client has no Senior CA yet. Choose who leads it: they sign off its books.
        </p>
      )}
      <div className={split ? 'grid items-start gap-x-10 gap-y-6 lg:grid-cols-2' : 'contents'}>
      <Field
        label="Senior CA in charge"
        hint={canSetLead ? 'They sign off this client’s entries. Staff work under them.' : 'Only a firm administrator changes this.'}
      >
        {(p) => (
          split ? (
            <Listbox
              {...p}
              disabled={!canSetLead || setLead.isPending}
              value={row.lead?.id ?? ''}
              onValueChange={(lead) => void run(() => setLead.mutateAsync({ clientId, lead: lead || null }), lead ? 'Senior CA set' : 'Senior CA removed')}
              options={[{ value: '', label: 'Not assigned' }, ...leads.map((l) => ({ value: l.id, label: `${l.name} (${l.role_display})` }))]}
            />
          ) : (
            <Select
              {...p}
              ref={leadRef}
              disabled={!canSetLead || setLead.isPending}
              value={row.lead?.id ?? ''}
              onChange={(e) => {
                const lead = e.target.value || null
                void run(() => setLead.mutateAsync({ clientId, lead }), lead ? 'Senior CA set' : 'Senior CA removed')
              }}
            >
              <option value="">Not assigned</option>
              {leads.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.role_display})
                </option>
              ))}
            </Select>
          )
        )}
      </Field>

      <div>
        <h3 className={split ? 'mb-2 text-sm text-muted-foreground' : 'mb-2 text-[13px] font-semibold text-heading'}>People working on this client</h3>
        {row.team.length === 0 ? (
          <p className={split ? 'text-base text-heading' : 'text-sm text-muted-foreground'}>Nobody is assigned yet. People with access to every client can still open it.</p>
        ) : (
          <ul className="divide-y rounded-lg border bg-card text-sm">
            {row.team.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-2">
                <span>
                  <span className="font-medium">{p.name}</span> <span className="text-muted-foreground">{p.role_display}</span>
                  {!p.is_active && (
                    <Badge tone="warning" className="ml-2">
                      Deactivated
                    </Badge>
                  )}
                  <span className="num ml-2 text-[13px] text-muted-foreground">since {formatDate(p.assigned_at)}</span>
                </span>
                <Button variant="ghost" size="sm" onClick={() => setRemoving({ id: p.id, name: p.name })} aria-label={`Take ${p.name} off this client`}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        {addable.length > 0 && (
          <form
            className="mt-3 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (!pick) return
              void run(() => assign.mutateAsync({ clientId, member: pick }), 'Added to the client').then(() => setPick(''))
            }}
          >
            <Field label="Add a person">
              {(p) => (
                split ? (
                  <Listbox
                    {...p}
                    className="min-w-56"
                    value={pick}
                    onValueChange={setPick}
                    options={[{ value: '', label: 'Choose…' }, ...addable.map((m) => ({ value: m.id, label: `${m.name} (${m.role_display})` }))]}
                  />
                ) : (
                  <Select {...p} className="min-w-56" value={pick} onChange={(e) => setPick(e.target.value)}>
                    <option value="">Choose…</option>
                    {addable.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} ({m.role_display})
                      </option>
                    ))}
                  </Select>
                )
              )}
            </Field>
            <Button type="submit" disabled={!pick || assign.isPending}>
              Add
            </Button>
          </form>
        )}
      </div>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Confirm
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={removing ? `Take ${removing.name} off this client?` : ''}
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          await unassign.mutateAsync({ clientId, member: removing!.id })
          toast.success('Removed from the client')
        }}
      >
        <p>They will no longer see this client, unless their access covers every client. What they already did stays on the books.</p>
      </Confirm>
    </section>
  )
}

type DetailField = 'name' | 'profile' | 'fy'

/** One fact as a row: its value and an Edit button, or, while editing, its field with Save and Cancel. */
function FactRow({
  title,
  hint,
  value,
  editing,
  onEdit,
  onCancel,
  onSave,
  saving,
  changed,
  error,
  lockedLabel,
  children,
}: {
  title: string
  hint?: string
  value: ReactNode
  editing: boolean
  onEdit?: () => void
  onCancel: () => void
  onSave: () => void
  saving: boolean
  changed: boolean
  error?: string | null
  lockedLabel?: string
  children: ReactNode
}) {
  if (editing) {
    return (
      <form
        className="grid gap-3 border-t py-4 first:border-t-0"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          onSave()
        }}
      >
        {children}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Button type="submit" size="sm" disabled={!changed || saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    )
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t py-4 first:border-t-0">
      <div className="min-w-0 flex-1 basis-56">
        <dt className="text-xs text-muted-foreground">{title}</dt>
        <dd className="mt-0.5 text-sm font-medium text-heading">{value}</dd>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
      {lockedLabel ? (
        <Badge tone="attention">{lockedLabel}</Badge>
      ) : (
        onEdit && (
          <Button size="sm" variant="secondary" onClick={onEdit} aria-label={`Edit ${title.toLowerCase()}`}>
            Edit
          </Button>
        )
      )}
    </div>
  )
}

function DetailsRows({ client }: { client: Client }) {
  const update = useUpdateClient(client.id)
  // Entries are numbered by financial year, so once one exists the year cannot move. Said before they try.
  const entries = useQuery({
    queryKey: ['client', client.id, 'entry-count'],
    queryFn: () => raw.get<Page<unknown>>(`${V1}/journal-entries/`, { client: client.id, page_size: 1 }),
  })
  const locked = (entries.data?.count ?? 0) > 0
  const [editing, setEditing] = useState<DetailField | null>(null)
  const [name, setName] = useState(client.name)
  const [profile, setProfile] = useState(client.business_profile ?? '')
  const [fy, setFy] = useState(formatDate(client.fy_start))
  const [error, setError] = useState<string | null>(null)

  const fyIso = parseDate(fy)
  const stop = () => {
    setEditing(null)
    setError(null)
    setName(client.name)
    setProfile(client.business_profile ?? '')
    setFy(formatDate(client.fy_start))
  }
  const start = (f: DetailField) => () => {
    setError(null)
    setEditing(f)
  }

  async function save() {
    setError(null)
    if (name.trim().length < 2) return setError('Enter the client’s name (at least 2 characters).')
    if (!locked && (!fyIso || !fyIso.endsWith('-01'))) return setError('The financial year must start on the 1st of a month, for example 01-04-2025.')
    try {
      await update.mutateAsync({ name: name.trim(), business_profile: profile.trim(), ...(locked || !fyIso ? {} : { fy_start: fyIso }) })
      toast.success('Client details saved')
      setEditing(null)
    } catch (err) {
      setError(messageOf(err))
    }
  }

  const common = { onCancel: stop, onSave: () => void save(), saving: update.isPending, error }
  return (
    <section aria-labelledby="ct-details" className="rounded-xl border border-border-strong bg-surface-2 p-6">
      <h2 id="ct-details" className="text-[15px] font-semibold text-heading">
        Client details
      </h2>
      <dl className="mt-2">
        <FactRow {...common} title="Client name" value={client.name} editing={editing === 'name'} onEdit={start('name')} changed={name.trim() !== client.name}>
          <Field label="Client name">{(p) => <Input {...p} autoFocus autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        </FactRow>
        <FactRow
          {...common}
          title="What the business does"
          hint="Helps the assistant suggest the right ledgers."
          value={client.business_profile || <span className="font-normal text-muted-foreground">Not added</span>}
          editing={editing === 'profile'}
          onEdit={start('profile')}
          changed={profile.trim() !== (client.business_profile ?? '')}
        >
          <Field label="What the business does" hint="Helps the assistant suggest the right ledgers.">
            {(p) => <Textarea {...p} autoFocus rows={3} maxLength={2000} value={profile} onChange={(e) => setProfile(e.target.value)} />}
          </Field>
        </FactRow>
        <FactRow
          {...common}
          title="Financial year starts"
          hint={locked ? 'This client has entries, and they are numbered by financial year.' : 'Normally 01-04-YYYY. It locks once the first entry is posted.'}
          value={<span className="num">{formatDate(client.fy_start)}</span>}
          editing={editing === 'fy' && !locked}
          onEdit={locked ? undefined : start('fy')}
          lockedLabel={locked ? 'Locked' : undefined}
          changed={fyIso !== client.fy_start}
        >
          <Field label="Financial year starts" hint="Normally 01-04-YYYY. It locks once the first entry is posted.">
            {(p) => <DateInput {...p} autoFocus value={fy} onChange={(e) => setFy(e.target.value)} />}
          </Field>
        </FactRow>
      </dl>
    </section>
  )
}

/** The Senior CA and the people on a client as rows, each changed in place. `People` is the same block as a form. */
function TeamRows({ clientId, justCreated }: { clientId: string; justCreated: boolean }) {
  const clients = useQuery(teamClients())
  const members = useQuery(teamMembers())
  const setLead = useSetLead()
  const assign = useAssign()
  const unassign = useUnassign()
  const [changingLead, setChangingLead] = useState(false)
  const [adding, setAdding] = useState(false)
  const [pick, setPick] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [removing, setRemoving] = useState<{ id: string; name: string } | null>(null)

  if (clients.isPending || members.isPending) return <Spinner label="Loading the team…" />
  if (clients.error) return <ErrorState error={clients.error} retry={() => void clients.refetch()} />
  const row = clients.data?.results.find((c) => c.id === clientId)
  if (!row) return <p className="text-sm text-muted-foreground">You do not manage this client’s team.</p>

  const canSetLead = clients.data?.can.set_lead ?? false
  const needsLead = justCreated && !row.lead && canSetLead
  const leads = members.data?.leads ?? []
  const leadRole = leads.find((l) => l.id === row.lead?.id)?.role_display
  const assigned = new Set(row.team.map((p) => p.id))
  const addable = clients.data.assignable.filter((p) => !assigned.has(p.id))

  async function run(action: () => Promise<unknown>, done: string) {
    setError(null)
    try {
      await action()
      toast.success(done)
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <section aria-labelledby="ct-people" className="rounded-xl border border-border-strong bg-surface-2 p-6">
      <h2 id="ct-people" className="text-[15px] font-semibold text-heading">
        Senior CA and team
      </h2>
      {needsLead && (
        <p role="status" className="mt-3 rounded-md border border-info/30 bg-info-bg px-4 py-2.5 text-sm">
          This client has no Senior CA yet. Choose who leads it: they sign off its books.
        </p>
      )}
      <dl className="mt-2">
        {changingLead ? (
          <div className="grid gap-3 border-t py-4 first:border-t-0">
            <Field label="Senior CA in charge" hint="They sign off this client’s entries. Staff work under them.">
              {(p) => (
                <Select
                  {...p}
                  autoFocus
                  disabled={setLead.isPending}
                  value={row.lead?.id ?? ''}
                  onChange={(e) => {
                    const lead = e.target.value || null
                    void run(() => setLead.mutateAsync({ clientId, lead }), lead ? 'Senior CA set' : 'Senior CA removed').then(() => setChangingLead(false))
                  }}
                >
                  <option value="">Not assigned</option>
                  {leads.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name} ({l.role_display})
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <div>
              <Button size="sm" variant="ghost" onClick={() => setChangingLead(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t py-4 first:border-t-0">
            <div className="flex min-w-0 flex-1 basis-56 items-center gap-3">
              <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-muted text-[13px] font-semibold text-muted-foreground">
                {row.lead ? initials(row.lead.name) : '–'}
              </span>
              <div className="min-w-0">
                <dt className="text-xs text-muted-foreground">Senior CA in charge</dt>
                <dd className="mt-0.5 text-sm font-medium text-heading">
                  {row.lead ? (
                    <>
                      {row.lead.name}
                      {leadRole && <span className="ml-1.5 font-normal text-muted-foreground">{leadRole}</span>}
                    </>
                  ) : (
                    <Badge tone="attention">Not assigned</Badge>
                  )}
                </dd>
                {!canSetLead && <p className="text-xs text-muted-foreground">Only a firm administrator changes this.</p>}
              </div>
            </div>
            {canSetLead && (
              <Button size="sm" variant={row.lead ? 'secondary' : 'primary'} onClick={() => setChangingLead(true)}>
                {row.lead ? 'Change' : 'Choose'}
              </Button>
            )}
          </div>
        )}

        <div className="border-t py-4">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="min-w-0 flex-1 basis-56">
              <dt className="text-xs text-muted-foreground">People working on this client</dt>
              {row.team.length === 0 && <dd className="mt-0.5 text-sm text-muted-foreground">Nobody is assigned yet. People with access to every client can still open it.</dd>}
            </div>
            {addable.length > 0 && !adding && (
              <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
                Add a person
              </Button>
            )}
          </div>
          {row.team.length > 0 && (
            <ul className="mt-2 divide-y rounded-lg border text-sm">
              {row.team.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-2">
                  <span>
                    <span className="font-medium">{p.name}</span> <span className="text-muted-foreground">{p.role_display}</span>
                    {!p.is_active && (
                      <Badge tone="warning" className="ml-2">
                        Deactivated
                      </Badge>
                    )}
                    <span className="num ml-2 text-[13px] text-muted-foreground">since {formatDate(p.assigned_at)}</span>
                  </span>
                  <Button variant="ghost" size="sm" onClick={() => setRemoving({ id: p.id, name: p.name })} aria-label={`Take ${p.name} off this client`}>
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {adding && (
            <form
              className="mt-3 flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (!pick) return
                void run(() => assign.mutateAsync({ clientId, member: pick }), 'Added to the client').then(() => {
                  setPick('')
                  setAdding(false)
                })
              }}
            >
              <Field label="Add a person">
                {(p) => (
                  <Select {...p} autoFocus className="min-w-56" value={pick} onChange={(e) => setPick(e.target.value)}>
                    <option value="">Choose…</option>
                    {addable.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} ({m.role_display})
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Button type="submit" disabled={!pick || assign.isPending}>
                Add
              </Button>
              <Button type="button" variant="ghost" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </form>
          )}
        </div>
      </dl>
      {error && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <Confirm
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={removing ? `Take ${removing.name} off this client?` : ''}
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          await unassign.mutateAsync({ clientId, member: removing!.id })
          toast.success('Removed from the client')
        }}
      >
        <p>They will no longer see this client, unless their access covers every client. What they already did stays on the books.</p>
      </Confirm>
    </section>
  )
}
