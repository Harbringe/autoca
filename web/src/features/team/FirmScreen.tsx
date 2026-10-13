// Firm settings: one sheet. The firm's details sit in sections on the left, a preview of where its name shows on the right, and a bar at the
// bottom appears when something has changed: nothing is saved until the bar says so, and Discard puts it back.
//
// Only a firm administrator has this screen. Only the owner may hand ownership on, and only to
// another active administrator, which the server enforces; the list offered here is those people.

import { useQuery } from '@tanstack/react-query'
import { CircleX } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { toast } from '@/lib/toast'
import { messageOf } from '@/api/errors'
import { firmSettings, useRenameFirm, useTransferOwner } from '@/api/queries/team'
import type { FirmSettings } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'
import { usePageTitle } from '@/lib/title'
import { initialsOf } from '@/lib/useDebounced'
import { useSession } from '@/session/session'
import { FIGURES, FigureDialog, type Figure } from './FirmFigures'

export function FirmScreen() {
  usePageTitle('Firm settings')
  const { can, refresh } = useSession()
  const firm = useQuery({ ...firmSettings(), enabled: can('firm.manage') })
  if (!can('firm.manage')) return <EmptyState title="Not available">Firm settings are for firm administrators.</EmptyState>
  if (firm.isPending) return <Spinner label="Loading the firm…" />
  if (firm.error) return <ErrorState error={firm.error} retry={() => void firm.refetch()} />
  return <FirmSheet f={firm.data} onSaved={() => void refresh()} />
}

/** A framed section of the sheet: a heading on a tinted band, then label-and-value rows. */
function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="overflow-hidden rounded-xl border bg-card">
      <div className="border-b bg-background px-5 py-3.5">
        <h3 id={id} className="text-[15px] font-semibold text-heading">
          {title}
        </h3>
      </div>
      {children}
    </section>
  )
}

function SheetRow({ label, htmlFor, children }: { label: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start gap-x-6 gap-y-1.5 border-b px-5 py-4 last:border-b-0">
      <label htmlFor={htmlFor} className="w-44 shrink-0 pt-2 text-sm text-muted-foreground max-sm:w-full max-sm:pt-0">
        {label}
      </label>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

/** The firm's name where it shows: the sidebar tile, and the head of a printed report. It follows what is typed, before anything is saved. */
function Preview({ name, counts, onOpen }: { name: string; counts: FirmSettings['counts']; onOpen: (figure: Figure) => void }) {
  const shown = name.trim() || 'Your firm'
  const count: Record<Figure, number> = { people: counts.active_members, senior: counts.senior_cas, staff: counts.staff, clients: counts.clients }
  return (
    <aside aria-label="Preview" className="grid content-start gap-3 lg:sticky lg:top-4 lg:self-start">
      <h3 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Preview</h3>
      <div className="flex items-center gap-3 rounded-xl border bg-sidebar p-3 text-sidebar-foreground">
        <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand text-[13px] font-bold text-white">
          {initialsOf(shown).slice(0, 2)}
        </span>
        <span className="min-w-0">
          <b className="block truncate text-sm text-white">{shown}</b>
          <span className="block text-xs">Sidebar</span>
        </span>
      </div>
      {/* A sheet of paper stays white in either theme, as a printed report does. */}
      <div role="img" aria-label={`A printed report headed ${shown}`} className="rounded-md border border-[#d6d1bf] bg-white p-5 text-[13px] text-[#14181a]">
        <h4 className="truncate text-base font-semibold">{shown}</h4>
        <p className="mt-0.5 text-[#4f5753]">Balance sheet as at 31-03-2026</p>
        <hr className="my-3 border-[#d6d1bf]" />
        {[90, 76, 84, 60].map((w) => (
          <div key={w} className="mt-2 h-2 rounded bg-[#e6e9e5]" style={{ width: `${w}%` }} />
        ))}
      </div>
      <h3 className="mt-3 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">The firm today</h3>
      <ul className="flex flex-wrap gap-2 text-[13px]">
        {FIGURES.map((fig) => (
          <li key={fig.id}>
            <button
              type="button"
              onClick={() => onOpen(fig.id)}
              title={`See ${fig.title.toLowerCase()}`}
              aria-haspopup="dialog"
              className="rounded-full border bg-card px-3 py-1 transition-colors duration-150 hover:bg-hover focus-visible:bg-hover"
            >
              {fig.label} <b className="num">{count[fig.id]}</b>
            </button>
          </li>
        ))}
      </ul>
      <p className="text-[13px] text-muted-foreground">{plural(counts.active_members, 'person', 'people')} can sign in. Press a figure to see who.</p>
    </aside>
  )
}

function FirmSheet({ f, onSaved }: { f: FirmSettings; onSaved: () => void }) {
  const rename = useRenameFirm()
  const [name, setName] = useState(f.name)
  const [error, setError] = useState<string | null>(null)
  const noteId = useId()
  const [figure, setFigure] = useState<Figure | null>(null)
  const dirty = name.trim() !== f.name
  const others = f.admins.filter((a) => !a.is_owner)

  async function save() {
    setError(null)
    if (!name.trim()) return setError('Enter the firm’s name.')
    try {
      await rename.mutateAsync(name.trim())
      toast.success('Firm name saved')
      onSaved()
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <div className="grid gap-4">
      <PageHeader title="Firm settings" description={`Created ${formatDate(f.created_at)}`} className="mb-0" />
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (dirty) void save()
        }}
        noValidate
        className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_380px]"
      >
        <div className="grid gap-4">
          <Section id="firm-name" title="Firm">
            <SheetRow label="Name on the books" htmlFor="firm-name-input">
              <Input
                id="firm-name-input"
                className="max-w-sm"
                autoComplete="off"
                disabled={!f.can.rename}
                value={name}
                aria-invalid={!!error}
                aria-describedby={noteId}
                onChange={(e) => {
                  setName(e.target.value)
                  setError(null)
                }}
              />
              <p id={noteId} className="mt-1.5 text-[13px] text-muted-foreground">
                Shown in the sidebar and on printed reports.
              </p>
              {error && (
                <p role="alert" className="mt-1.5 flex items-center gap-1.5 text-[13px] text-destructive">
                  <CircleX className="size-4" aria-hidden /> {error}
                </p>
              )}
            </SheetRow>
          </Section>

          <Section id="firm-owner" title="Owner and administrators">
            <SheetRow label="Owner">
              <p className="flex items-center gap-2 pt-2 text-sm">
                <span className="font-medium">{f.owner?.name ?? 'Nobody yet'}</span>
                {f.owner && <Badge tone="info">Owner</Badge>}
              </p>
            </SheetRow>
            <SheetRow label="Administrators">
              {others.length ? (
                <ul className="grid gap-1.5 pt-2 text-sm">
                  {others.map((a) => (
                    <li key={a.id} className="flex items-center gap-2">
                      <span className="font-medium">{a.name}</span>
                      <Badge tone="done">Administrator</Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="pt-2 text-sm text-muted-foreground">None yet. Make a person an administrator on the Team page.</p>
              )}
            </SheetRow>
            <SheetRow label="Ownership">
              {f.can.transfer ? <Transfer admins={others} /> : <p className="pt-2 text-[13px] text-muted-foreground">Only the firm owner can hand ownership to another administrator.</p>}
            </SheetRow>
          </Section>
        </div>

        <Preview name={name} counts={f.counts} onOpen={setFigure} />

        {dirty && (
          <div
            role="region"
            aria-label="Unsaved changes"
            className="rise sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary bg-card px-5 py-3 shadow-[var(--shadow-float)] lg:col-span-2"
          >
            <span className="text-sm">
              <b className="text-heading">Unsaved changes</b> <span className="text-muted-foreground">on this page</span>
            </span>
            <span className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setName(f.name)
                  setError(null)
                }}
              >
                Discard
              </Button>
              <Button type="submit" disabled={!name.trim() || rename.isPending}>
                {rename.isPending ? 'Saving…' : 'Save changes'}
              </Button>
            </span>
          </div>
        )}
      </form>
      <FigureDialog figure={figure} onClose={() => setFigure(null)} />
    </div>
  )
}

function Transfer({ admins }: { admins: { id: string; name: string }[] }) {
  const transfer = useTransferOwner()
  const [pick, setPick] = useState('')
  const [asking, setAsking] = useState(false)
  const target = admins.find((a) => a.id === pick)

  if (!admins.length) return <p className="pt-2 text-[13px] text-muted-foreground">To hand ownership on, first make another person a firm administrator on the Team page.</p>

  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="Transfer ownership to" className="max-w-xs" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">Choose an administrator…</option>
          {admins.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <Button type="button" variant="outline" disabled={!target} onClick={() => setAsking(true)}>
          Hand over ownership…
        </Button>
      </div>
      <p className="text-[13px] text-muted-foreground">They must be an active firm administrator. You stay an administrator.</p>
      <Confirm
        open={asking}
        onOpenChange={setAsking}
        title={target ? `Make ${target.name} the firm owner?` : ''}
        confirmLabel={target ? `Make ${target.name} the owner` : 'Transfer'}
        destructive
        onConfirm={async () => {
          await transfer.mutateAsync(pick)
          toast.success(`${target?.name} is now the firm owner`)
          setPick('')
        }}
      >
        <p>{target?.name} will own the firm and be the only person who can transfer ownership or manage other administrators.</p>
        <p>You stay an administrator, but you can no longer undo this yourself.</p>
      </Confirm>
    </div>
  )
}
