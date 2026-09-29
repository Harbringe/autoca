// Firm settings: the firm's name, who owns it, and who administers it.
//
// Only a firm administrator has this screen. Only the owner may hand ownership on, and only to
// another active administrator, which the server enforces; the list offered here is those people.

import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { firmSettings, useRenameFirm, useTransferOwner } from '@/api/queries/team'
import { Confirm } from '@/components/ca/Confirm'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'
import { usePageTitle } from '@/lib/title'
import { useSession } from '@/session/session'

export function FirmScreen() {
  usePageTitle('Firm settings')
  const { can, refresh } = useSession()
  const firm = useQuery({ ...firmSettings(), enabled: can('firm.manage') })
  if (!can('firm.manage')) return <EmptyState title="Not available">Firm settings are for firm administrators.</EmptyState>
  if (firm.isPending) return <Spinner label="Loading the firm…" />
  if (firm.error) return <ErrorState error={firm.error} retry={() => void firm.refetch()} />
  const f = firm.data

  return (
    <div className="grid max-w-3xl gap-8">
      <PageHeader title="Firm settings" description={`Created ${formatDate(f.created_at)}`} className="mb-0" />

      <Rename name={f.name} allowed={f.can.rename} onSaved={() => void refresh()} />

      <section aria-labelledby="firm-owner" className="grid gap-3">
        <h2 id="firm-owner" className="text-base font-semibold">
          Owner and administrators
        </h2>
        <p className="text-sm">
          Owner: <span className="font-medium">{f.owner?.name ?? 'Nobody yet'}</span>
        </p>
        <ul className="divide-y rounded-lg border bg-card text-sm">
          {f.admins.map((a) => (
            <li key={a.id} className="flex items-center gap-2 px-4 py-2">
              <span className="font-medium">{a.name}</span>
              {a.is_owner && <Badge tone="info">Owner</Badge>}
            </li>
          ))}
        </ul>
        {f.can.transfer ? (
          <Transfer admins={f.admins.filter((a) => !a.is_owner)} />
        ) : (
          <p className="text-[13px] text-muted-foreground">Only the firm owner can hand ownership to another administrator.</p>
        )}
      </section>

      <section aria-labelledby="firm-counts">
        <h2 id="firm-counts" className="mb-2 text-base font-semibold">
          The firm today
        </h2>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(
            [
              ['Active people', f.counts.active_members],
              ['Senior CAs', f.counts.senior_cas],
              ['Staff and read-only', f.counts.staff],
              ['Clients', f.counts.clients],
            ] as const
          ).map(([label, n]) => (
            <div key={label} className="rounded-lg border bg-card p-3">
              <dt className="text-[13px] text-muted-foreground">{label}</dt>
              <dd className="num mt-0.5 text-2xl font-semibold">{n}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-[13px] text-muted-foreground">{plural(f.counts.active_members, 'person', 'people')} can sign in.</p>
      </section>
    </div>
  )
}

function Rename({ name, allowed, onSaved }: { name: string; allowed: boolean; onSaved: () => void }) {
  const rename = useRenameFirm()
  const [value, setValue] = useState(name)
  const [error, setError] = useState<string | null>(null)
  const changed = value.trim() !== name

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!value.trim()) return setError('Enter the firm’s name.')
    try {
      await rename.mutateAsync(value.trim())
      toast.success('Firm name saved')
      onSaved()
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <section aria-labelledby="firm-name">
      <h2 id="firm-name" className="mb-3 text-base font-semibold">
        Firm name
      </h2>
      <form onSubmit={submit} className="flex flex-wrap items-start gap-2" noValidate>
        <div className="w-full max-w-sm">
          <Field label="Name on the books" hint="Shown in the sidebar and on printed reports." error={error ?? undefined}>
            {(p) => <Input {...p} autoComplete="off" disabled={!allowed} value={value} onChange={(e) => setValue(e.target.value)} />}
          </Field>
        </div>
        <Button type="submit" className="mt-6" disabled={!allowed || !changed || rename.isPending}>
          {rename.isPending ? 'Saving…' : 'Save name'}
        </Button>
      </form>
    </section>
  )
}

function Transfer({ admins }: { admins: { id: string; name: string }[] }) {
  const transfer = useTransferOwner()
  const [pick, setPick] = useState('')
  const [asking, setAsking] = useState(false)
  const target = admins.find((a) => a.id === pick)

  if (!admins.length)
    return <p className="text-[13px] text-muted-foreground">To hand ownership on, first make another person a firm administrator on the Team page.</p>

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="w-full max-w-sm">
        <Field label="Transfer ownership to" hint="They must be an active firm administrator. You stay an administrator.">
          {(p) => (
            <Select {...p} value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Choose an administrator…</option>
              {admins.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <Button variant="outline" disabled={!target} onClick={() => setAsking(true)}>
        Transfer…
      </Button>
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
