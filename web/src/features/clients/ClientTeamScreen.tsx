// A client's people and details: who leads it, who works on it, and its name, description and
// financial year. Everything offered follows the caller's permissions; the server checks again.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { clientDetail, useUpdateClient, V1 } from '@/api/queries/clients'
import { teamClients, teamMembers, useAssign, useSetLead, useUnassign } from '@/api/queries/team'
import type { Client, Page } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, Textarea } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, parseDate } from '@/lib/format'
import { useSession } from '@/session/session'

export function ClientTeamScreen({ clientId, justCreated }: { clientId: string; justCreated: boolean }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  if (client.isPending) return <Spinner label="Loading…" />
  if (client.error) return <ErrorState error={client.error} retry={() => void client.refetch()} />
  return (
    <div className="grid max-w-5xl items-start gap-4 lg:grid-cols-2">
      {can('team.view') && <People clientId={clientId} justCreated={justCreated} />}
      {can('client.update') && <Details client={client.data} />}
    </div>
  )
}

export function People({ clientId, justCreated }: { clientId: string; justCreated: boolean }) {
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
    <section aria-labelledby="ct-people" className="grid gap-5 rounded-lg border bg-card p-5">
      <h2 id="ct-people" className="text-[15px] font-semibold text-heading">
        Senior CA and team
      </h2>
      {needsLead && (
        <p role="status" className="rounded-md border border-info/30 bg-info-bg px-4 py-2.5 text-sm">
          This client has no Senior CA yet. Choose who leads it: they sign off its books.
        </p>
      )}
      <Field
        label="Senior CA in charge"
        hint={canSetLead ? 'They sign off this client’s entries. Staff work under them.' : 'Only a firm administrator changes this.'}
      >
        {(p) => (
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
        )}
      </Field>

      <div>
        <h3 className="mb-2 text-[13px] font-semibold text-heading">People working on this client</h3>
        {row.team.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nobody is assigned yet. People with access to every client can still open it.</p>
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
                <Select {...p} className="min-w-56" value={pick} onChange={(e) => setPick(e.target.value)}>
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
          </form>
        )}
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

function Details({ client }: { client: Client }) {
  const update = useUpdateClient(client.id)
  // Entries are numbered by financial year, so once one exists the year cannot move. Said before they try.
  const entries = useQuery({
    queryKey: ['client', client.id, 'entry-count'],
    queryFn: () => raw.get<Page<unknown>>(`${V1}/journal-entries/`, { client: client.id, page_size: 1 }),
  })
  const locked = (entries.data?.count ?? 0) > 0
  const [name, setName] = useState(client.name)
  const [profile, setProfile] = useState(client.business_profile ?? '')
  const [fy, setFy] = useState(formatDate(client.fy_start))
  const [error, setError] = useState<string | null>(null)

  const fyIso = parseDate(fy)
  const changed = name.trim() !== client.name || profile.trim() !== (client.business_profile ?? '') || (!locked && fyIso !== client.fy_start)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (name.trim().length < 2) return setError('Enter the client’s name (at least 2 characters).')
    if (!locked && (!fyIso || !fyIso.endsWith('-01'))) return setError('The financial year must start on the 1st of a month, for example 01-04-2025.')
    try {
      await update.mutateAsync({ name: name.trim(), business_profile: profile.trim(), ...(locked || !fyIso ? {} : { fy_start: fyIso }) })
      toast.success('Client details saved')
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <section aria-labelledby="ct-details" className="rounded-lg border bg-card p-5">
      <h2 id="ct-details" className="mb-3 text-[15px] font-semibold text-heading">
        Client details
      </h2>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <Field label="Client name">{(p) => <Input {...p} autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="What the business does" hint="Helps the assistant suggest the right ledgers.">
          {(p) => <Textarea {...p} rows={3} maxLength={2000} value={profile} onChange={(e) => setProfile(e.target.value)} />}
        </Field>
        <Field
          label="Financial year starts"
          hint={locked ? 'Locked: this client has entries, and they are numbered by financial year.' : 'Normally 01-04-YYYY. It locks once the first entry is posted.'}
        >
          {(p) => <DateInput {...p} value={fy} readOnly={locked} disabled={locked} onChange={(e) => setFy(e.target.value)} />}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div>
          <Button type="submit" disabled={!changed || update.isPending}>
            {update.isPending ? 'Saving…' : 'Save details'}
          </Button>
        </div>
      </form>
    </section>
  )
}
