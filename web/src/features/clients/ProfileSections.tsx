// The client's profile: who they are, what they are registered as, how to reach them, and the firm's own notes.
//
// Each section shows its facts and, for a person who may edit, one Edit button that turns the whole section into a
// form with Save and Cancel. Registration numbers are masked by the server for anyone who may not edit.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type FormEvent, type ReactNode } from 'react'
import { toast } from '@/lib/toast'
import { messageOf } from '@/api/errors'
import { clientDetail, clientProfile, useUpdateProfile, type ClientProfile } from '@/api/queries/clients'
import { gstRegistrations } from '@/api/queries/gst'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, Textarea } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/format'
import { useSession } from '@/session/session'
import { initials } from './clientsView'
import { CONSTITUTIONS, draftOf, labelOf, MSME_CATEGORIES, patchOf, type FieldDef } from './profileView'

const CARD = 'rounded-xl border border-border-strong bg-surface-2 p-6'

const IDENTITY: FieldDef[] = [
  { key: 'constitution', label: 'Constitution', kind: 'select', options: CONSTITUTIONS, hint: 'What kind of person or body the client is.' },
  { key: 'trade_name', label: 'Trade name', kind: 'text', hint: 'If the client trades under another name.', maxLength: 255 },
  { key: 'incorporated_on', label: 'Incorporated or started on', kind: 'date' },
  { key: 'client_since', label: 'Client since', kind: 'date', hint: 'When your firm began acting for them.' },
]

const REGISTRATIONS: FieldDef[] = [
  { key: 'pan', label: 'PAN', kind: 'id', maxLength: 10 },
  { key: 'tan', label: 'TAN', kind: 'id', maxLength: 10, hint: 'Needed for TDS returns.' },
  { key: 'cin', label: 'CIN or LLPIN', kind: 'id', maxLength: 21, hint: 'A company’s CIN, or an LLP’s LLPIN.' },
  { key: 'udyam', label: 'Udyam (MSME) number', kind: 'id', maxLength: 24, hint: 'Like UDYAM-MH-12-1234567.' },
  { key: 'msme_category', label: 'MSME category', kind: 'select', options: MSME_CATEGORIES },
]

const CONTACTS: FieldDef[] = [
  { key: 'contact_name', label: 'Contact person', kind: 'text', maxLength: 255 },
  { key: 'contact_phone', label: 'Phone', kind: 'tel', maxLength: 32 },
  { key: 'contact_email', label: 'Email', kind: 'email', maxLength: 254 },
  { key: 'contact2_name', label: 'Second contact', kind: 'text', maxLength: 255 },
  { key: 'contact2_phone', label: 'Second contact’s phone', kind: 'tel', maxLength: 32 },
  { key: 'contact2_email', label: 'Second contact’s email', kind: 'email', maxLength: 254 },
  { key: 'address', label: 'Address', kind: 'area', wide: true, maxLength: 1000 },
]

const NOTES: FieldDef[] = [
  { key: 'notes', label: 'Notes', kind: 'area', wide: true, maxLength: 4000, hint: 'For your firm only. Never shown to the assistant.' },
]

/** The client at a glance: initials, name, what they are, since when, and who last edited the profile. */
export function ProfileHeader({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const profile = useQuery({ ...clientProfile(clientId), enabled: can('client.view') })
  if (!client.data) return null
  const p = profile.data
  const kind = labelOf(CONSTITUTIONS, p?.constitution)
  const edited = p?.profile_updated_at ? `${formatDate(p.profile_updated_at.slice(0, 10))}${p.profile_updated_by ? ` by ${p.profile_updated_by}` : ''}` : null
  return (
    <section aria-label="Client" className={`${CARD} flex flex-wrap items-center gap-x-6 gap-y-4`}>
      <span aria-hidden className="grid size-[72px] shrink-0 place-items-center rounded-2xl border border-border-strong bg-background text-2xl font-semibold text-heading">
        {initials(client.data.name)}
      </span>
      <div className="min-w-0 flex-1 basis-64">
        <h2 className="truncate text-2xl font-semibold leading-tight text-heading">{client.data.name}</h2>
        {p?.trade_name && <p className="mt-0.5 text-sm text-muted-foreground">Trades as {p.trade_name}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {kind && (
            <Badge tone="neutral" icon={false} className="h-7 rounded-full px-3 text-[13px]">
              {kind}
            </Badge>
          )}
          {p?.msme_category && (
            <Badge tone="info" icon={false} className="h-7 rounded-full px-3 text-[13px]">
              MSME · {labelOf(MSME_CATEGORIES, p.msme_category)}
            </Badge>
          )}
          <span className="text-sm text-muted-foreground">
            Financial year from <span className="num text-heading">{formatDate(client.data.fy_start)}</span>
            {p?.client_since && (
              <>
                {' · '}Client since <span className="num text-heading">{formatDate(p.client_since)}</span>
              </>
            )}
          </span>
        </div>
      </div>
      {edited && <p className="text-[13px] text-muted-foreground">Profile last edited {edited}</p>}
    </section>
  )
}

/** Identity, registrations, contacts and notes, each its own card. */
export function ProfileSections({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const profile = useQuery({ ...clientProfile(clientId), enabled: can('client.view') })
  if (!can('client.view')) return null
  if (profile.isPending) return <Spinner label="Loading the profile…" />
  if (profile.error) return <ErrorState error={profile.error} retry={() => void profile.refetch()} />
  const p = profile.data
  return (
    <>
      <Section clientId={clientId} profile={p} title="About the client" fields={IDENTITY} />
      <Section clientId={clientId} profile={p} title="Registrations" fields={REGISTRATIONS} after={<GstinRow clientId={clientId} />} note={<SharedPan names={p.pan_shared_with} />} />
      <Section clientId={clientId} profile={p} title="Contacts and address" fields={CONTACTS} />
      <Section clientId={clientId} profile={p} title="Notes" fields={NOTES} />
    </>
  )
}

function SharedPan({ names }: { names: string[] }) {
  if (names.length === 0) return null
  return (
    <p role="status" className="rounded-md border border-accent-edge bg-accent px-4 py-2.5 text-sm text-accent-foreground">
      This PAN is also on {names.join(', ')}. That is right only if they are the same person or body.
    </p>
  )
}

function GstinRow({ clientId }: { clientId: string }) {
  const registrations = useQuery(gstRegistrations(clientId))
  const list = registrations.data ?? []
  return (
    <div className="sm:col-span-2">
      <dt className="text-sm text-muted-foreground">GSTIN</dt>
      <dd className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-base font-semibold text-heading">
        {list.length === 0 ? <span className="font-normal text-muted-foreground">Not added</span> : list.map((r) => <span key={r.id} className="num">{r.gstin}</span>)}
        <Link to="/clients/$clientId/gst" params={{ clientId }} className="text-sm font-semibold text-link underline underline-offset-2">
          Manage on the GST page
        </Link>
      </dd>
    </div>
  )
}

function Section({ clientId, profile, title, fields, after, note }: { clientId: string; profile: ClientProfile; title: string; fields: FieldDef[]; after?: ReactNode; note?: ReactNode }) {
  const update = useUpdateProfile(clientId)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const headingId = `profile-${title.toLowerCase().replace(/[^a-z]+/g, '-')}`
  const set = (key: string) => (value: string) => setDraft((d) => ({ ...d, [key]: value }))

  const begin = () => {
    setDraft(draftOf(profile, fields))
    setError(null)
    setEditing(true)
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const { patch, problem } = patchOf(profile, fields, draft)
    if (problem) return setError(problem)
    if (Object.keys(patch).length === 0) return setEditing(false)
    try {
      await update.mutateAsync(patch)
      toast.success(`${title} saved`)
      setEditing(false)
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <section aria-labelledby={headingId} className={CARD}>
      <div className="flex items-center justify-between gap-3">
        <h2 id={headingId} className="text-lg font-semibold text-heading">
          {title}
        </h2>
        {profile.can_edit && !editing && (
          <Button variant="outline" className="h-10 rounded-lg px-4 font-semibold text-heading dark:border-border-strong dark:bg-background dark:hover:bg-hover" onClick={begin} aria-label={`Edit ${title.toLowerCase()}`}>
            Edit
          </Button>
        )}
      </div>
      {editing ? (
        <form className="mt-4 grid gap-4" noValidate onSubmit={(e) => void save(e)}>
          {note}
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            {fields.map((f, i) => (
              <div key={f.key} className={f.wide ? 'sm:col-span-2' : undefined}>
                <Field label={f.label} hint={f.hint}>
                  {(p) =>
                    f.kind === 'select' ? (
                      <Select {...p} autoFocus={i === 0} value={draft[f.key] ?? ''} onChange={(e) => set(f.key)(e.target.value)}>
                        <option value="">Not set</option>
                        {f.options?.map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </Select>
                    ) : f.kind === 'area' ? (
                      <Textarea {...p} autoFocus={i === 0} rows={f.key === 'notes' ? 5 : 3} maxLength={f.maxLength} value={draft[f.key] ?? ''} onChange={(e) => set(f.key)(e.target.value)} />
                    ) : f.kind === 'date' ? (
                      <DateInput {...p} autoFocus={i === 0} value={draft[f.key] ?? ''} onChange={(e) => set(f.key)(e.target.value)} />
                    ) : (
                      <Input
                        {...p}
                        autoFocus={i === 0}
                        type={f.kind === 'email' ? 'email' : f.kind === 'tel' ? 'tel' : 'text'}
                        autoComplete="off"
                        autoCapitalize={f.kind === 'id' ? 'characters' : undefined}
                        className={f.kind === 'id' ? 'font-mono uppercase' : undefined}
                        maxLength={f.maxLength}
                        value={draft[f.key] ?? ''}
                        onChange={(e) => set(f.key)(e.target.value)}
                      />
                    )
                  }
                </Field>
              </div>
            ))}
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex gap-3">
            <Button type="submit" size="lg" className="rounded-lg px-6 font-semibold" loading={update.isPending}>
              {update.isPending ? 'Saving…' : 'Save'}
            </Button>
            <Button type="button" size="lg" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <>
          {note && <div className="mt-4">{note}</div>}
          <dl className="mt-4 grid gap-x-6 gap-y-5 sm:grid-cols-2">
            {fields.map((f) => (
              <Fact key={f.key} def={f} profile={profile} />
            ))}
            {after}
          </dl>
        </>
      )}
    </section>
  )
}

function Fact({ def, profile }: { def: FieldDef; profile: ClientProfile }) {
  const raw = (profile as unknown as Record<string, string | null | undefined>)[def.key] ?? ''
  const shown = def.kind === 'date' && raw ? formatDate(raw) : def.kind === 'select' ? labelOf(def.options ?? [], raw) : raw
  return (
    <div className={def.wide ? 'sm:col-span-2' : undefined}>
      <dt className="text-sm text-muted-foreground">{def.label}</dt>
      <dd className={`mt-1 whitespace-pre-line break-words text-base font-semibold text-heading ${def.kind === 'id' || def.kind === 'date' ? 'num' : ''}`}>
        {shown || <span className="font-normal text-muted-foreground">Not added</span>}
      </dd>
    </div>
  )
}
