// The two dialogs of the Team screen: inviting a person, and editing one.
//
// The screen offers only what the server's `can` flags allow; the server still decides, and its
// sentence ("Sen still leads 2 clients. Move them to someone else first.") is shown as it is.

import { useState, type FormEvent } from 'react'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { useInvitePerson, useUpdateMember, type InviteCreated } from '@/api/queries/team'
import type { Member, MembersResponse, Person, Role } from '@/api/types'
import { ROLE_LABEL } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Checkbox, Select } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { formatDate } from '@/lib/format'
import { isTeamRole, memberPatch } from '@/lib/team'

const ROLE_HINT: Record<Role, string> = {
  FIRM_ADMIN: 'Sees every client and manages the firm.',
  SENIOR_CA: 'Reviews and signs off the books of the clients they lead.',
  STAFF: 'Prepares the books: uploads statements, places rows, posts entries.',
  READ_ONLY: 'Can look at the books, and change nothing.',
}

function ErrorLine({ message }: { message: string | null }) {
  return message ? (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  ) : null
}

function LeadSelect({
  id,
  value,
  onChange,
  leads,
  exclude,
  none,
  ...aria
}: {
  id: string
  value: string
  onChange: (v: string) => void
  leads: Person[]
  exclude?: string
  none: string
}) {
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} {...aria}>
      <option value="">{none}</option>
      {leads
        .filter((l) => l.id !== exclude)
        .map((l) => (
          <option key={l.id} value={l.id}>
            {l.name} ({l.role_display})
          </option>
        ))}
    </Select>
  )
}

export function InviteDialog({
  open,
  onOpenChange,
  info,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  info: MembersResponse
}) {
  const invite = useInvitePerson()
  const roles = info.can.invite_roles
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>(roles.includes('STAFF') ? 'STAFF' : roles[0]!)
  const [manager, setManager] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<InviteCreated | null>(null)
  // A Senior CA's invitations always go to their own team; only an administrator chooses.
  const chooseTeam = info.can.manage && isTeamRole(role)

  function close(next: boolean) {
    if (invite.isPending) return
    onOpenChange(next)
    if (!next) {
      setEmail('')
      setName('')
      setManager('')
      setError(null)
      setDone(null)
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) return setError('Enter their email address, for example asha@firm.in.')
    try {
      setDone(
        await invite.mutateAsync({
          email: email.trim(),
          full_name: name.trim() || undefined,
          role,
          manager: chooseTeam && manager ? manager : undefined,
        }),
      )
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{done ? 'Invitation ready' : 'Invite a person'}</DialogTitle>
          <DialogDescription>
            {done
              ? `Send ${done.email} this link. It works once and expires on ${formatDate(done.expires_at)}.`
              : 'They get a one-time link to create their sign-in. Nothing is emailed for you: you send the link.'}
          </DialogDescription>
        </DialogHeader>
        {done ? (
          <div className="grid gap-3">
            <div className="flex gap-2">
              <Input readOnly value={done.link} aria-label="Invitation link" onFocus={(e) => e.currentTarget.select()} />
              <Button
                variant="outline"
                onClick={() =>
                  navigator.clipboard
                    .writeText(done.link)
                    .then(() => toast.success('Link copied'))
                    .catch(() => toast.error('Could not copy. Select the link and copy it.'))
                }
              >
                <Copy /> Copy
              </Button>
            </div>
            <p className="text-[13px] text-muted-foreground">
              It is shown only now. If you lose it, invite the same address again: that replaces the old link.
            </p>
            <DialogFooter>
              <Button autoFocus onClick={() => close(false)}>
                Done
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <Field label="Email">{(p) => <Input {...p} type="email" autoFocus autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            <Field label="Name (optional)">{(p) => <Input {...p} autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
            <Field label="Role" hint={ROLE_HINT[role]}>
              {(p) => (
                <Select {...p} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                  {roles.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {chooseTeam && (
              <Field label="Team of" hint="The Senior CA they report to. You can change it later.">
                {(p) => <LeadSelect {...p} value={manager} onChange={setManager} leads={info.leads} none="No team yet" />}
              </Field>
            )}
            {!info.can.manage && <p className="text-[13px] text-muted-foreground">They will join your team.</p>}
            <ErrorLine message={error} />
            <DialogFooter>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={invite.isPending}>
                {invite.isPending ? 'Creating…' : 'Create invitation'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function EditMemberDialog({
  member,
  info,
  onClose,
}: {
  member: Member | null
  info: MembersResponse
  onClose: () => void
}) {
  return (
    <Dialog open={!!member} onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        {/* Keyed by person, so each opening starts from that person's current settings. */}
        {member && <EditForm key={member.id} member={member} info={info} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  )
}

function EditForm({ member, info, onClose }: { member: Member; info: MembersResponse; onClose: () => void }) {
  const update = useUpdateMember()
  const roles = info.can.invite_roles.includes(member.role) ? info.can.invite_roles : [member.role, ...info.can.invite_roles]
  const [role, setRole] = useState<Role>(member.role)
  const [manager, setManager] = useState(member.manager?.id ?? '')
  const [scopeAll, setScopeAll] = useState(member.scope_all_clients)
  const [keep, setKeep] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const patch = memberPatch(member, { role, manager: manager || null, scopeAll, keepAssignments: keep })
  const changed = Object.keys(patch).filter((k) => k !== 'keep_client_assignments').length > 0
  const movingTeam = 'manager' in patch && !!member.manager

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await update.mutateAsync({ id: member.id, patch })
      toast.success(`${member.name} updated`)
      onClose()
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{member.name}</DialogTitle>
        <DialogDescription>{member.email}</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <Field label="Role" hint={ROLE_HINT[role]}>
          {(p) => (
            <Select {...p} autoFocus value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {roles.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {isTeamRole(role) && (
          <Field label="Team of" hint="The Senior CA they report to.">
            {(p) => <LeadSelect {...p} value={manager} onChange={setManager} leads={info.leads} exclude={member.id} none="No team" />}
          </Field>
        )}
        {movingTeam && (
          <Checkbox
            label="Keep them on the clients they are already assigned to"
            checked={keep}
            onChange={(e) => setKeep(e.target.checked)}
          />
        )}
        {role !== 'FIRM_ADMIN' && (
          <Checkbox label="Can open every client, not only assigned ones" checked={scopeAll} onChange={(e) => setScopeAll(e.target.checked)} />
        )}
        <ErrorLine message={error} />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!changed || update.isPending}>
            {update.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </DialogFooter>
      </form>
    </>
  )
}
