// Inviting several people at once: paste a list (or choose a CSV), see what was read, send, and take the links away.
//
// The server answers for each row on its own, so one address that cannot be invited does not stop the others. Every link is shown
// only in that answer: copy them all, or download them, before closing.

import { Download, FileUp } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { messageOf } from '@/api/errors'
import { useInviteMany, type BulkRowResult } from '@/api/queries/team'
import type { MembersResponse, Role } from '@/api/types'
import { ROLE_LABEL } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, Textarea } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { plural } from '@/lib/format'
import { managerChoices as choicesFor } from '@/lib/team'
import { linksCsv, MAX_BULK_ROWS, parseInviteLines } from './bulkInvite'
import { copyText } from './LinkBox'

export function BulkInviteDialog({
  open,
  onOpenChange,
  info,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  info: MembersResponse
}) {
  const invite = useInviteMany()
  const roles = info.can.invite_roles
  const [text, setText] = useState('')
  const [role, setRole] = useState<Role>(roles.includes('STAFF') ? 'STAFF' : roles[0]!)
  const [manager, setManager] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<BulkRowResult[] | null>(null)
  const file = useRef<HTMLInputElement>(null)

  const parsed = parseInviteLines(text)
  const managerChoices = choicesFor(role, info.leads)
  // An administrator chooses who the people report to; a Senior CA's team is assigned on the server.
  const chooseTeam = info.can.manage && role !== 'FIRM_ADMIN'
  const defaultManager = chooseTeam && managerChoices.some((p) => p.id === manager) ? manager : undefined

  function close(next: boolean) {
    if (invite.isPending) return
    onOpenChange(next)
    if (!next) {
      setText('')
      setManager('')
      setError(null)
      setResults(null)
    }
  }

  async function readFile(list: FileList | null) {
    const chosen = list?.[0]
    if (!chosen) return
    try {
      setText(await chosen.text())
      setError(null)
    } catch {
      setError('That file could not be read. Paste the addresses instead.')
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (parsed.rows.length === 0) return setError('Add at least one email address, one to a line.')
    if (parsed.rows.length > MAX_BULK_ROWS) return setError(`Invite ${MAX_BULK_ROWS} people at a time at most. This list has ${parsed.rows.length}.`)
    try {
      const answer = await invite.mutateAsync(
        parsed.rows.map((r) => {
          const rowRole = r.role && roles.includes(r.role) ? r.role : role
          return { email: r.email, full_name: r.full_name, role: rowRole, manager: rowRole === role ? defaultManager : undefined }
        }),
      )
      setResults(answer.results)
    } catch (err) {
      setError(messageOf(err))
    }
  }

  const made = results?.filter((r) => r.ok) ?? []
  const refused = results?.filter((r) => !r.ok) ?? []

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent aria-describedby={undefined} className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{results ? 'Invitations ready' : 'Invite several people'}</DialogTitle>
          <DialogDescription>
            {results
              ? `${plural(made.length, 'link')} made${refused.length ? `, ${refused.length} could not be` : ''}. The links are shown only now: copy or download them before you close this.`
              : `One address to a line, with a name and role if you like (asha@firm.in, Asha Rao, Staff). Up to ${MAX_BULK_ROWS} at a time.`}
          </DialogDescription>
        </DialogHeader>

        {results ? (
          <div className="grid gap-3">
            <ul className="max-h-72 divide-y overflow-auto rounded-lg border text-sm" aria-label="Results">
              {results.map((r) => (
                <li key={r.email} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                  <span className="min-w-0 flex-1 truncate font-medium">{r.email}</span>
                  {r.ok ? (
                    <>
                      <Badge tone="success">{r.role_display}</Badge>
                      <Button variant="ghost" size="sm" onClick={() => void copyText(r.link!, 'Link copied')} aria-label={`Copy the link for ${r.email}`}>
                        Copy link
                      </Button>
                    </>
                  ) : (
                    <span className="text-[13px] text-destructive">{r.error}</span>
                  )}
                </li>
              ))}
            </ul>
            <DialogFooter>
              {made.length > 0 && (
                <>
                  <Button variant="outline" onClick={() => void copyText(made.map((r) => `${r.email}\t${r.link}`).join('\n'), 'All links copied')}>
                    Copy all links
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      const url = URL.createObjectURL(new Blob([linksCsv(made)], { type: 'text/csv' }))
                      const a = document.createElement('a')
                      a.href = url
                      a.download = 'invitation-links.csv'
                      a.click()
                      URL.revokeObjectURL(url)
                    }}
                  >
                    <Download /> Download CSV
                  </Button>
                </>
              )}
              <Button autoFocus onClick={() => close(false)}>
                Done
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <Field label="Email addresses">
              {(p) => (
                <Textarea
                  {...p}
                  rows={7}
                  autoFocus
                  spellCheck={false}
                  placeholder={'asha@firm.in\nBea Rao <bea@firm.in>\ncy@firm.in, Cy Das, Read only'}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              )}
            </Field>
            <div>
              <input ref={file} type="file" accept=".csv,.txt,text/csv,text/plain" className="sr-only" aria-label="Choose a CSV file" onChange={(e) => void readFile(e.target.files)} />
              <Button variant="outline" size="sm" onClick={() => file.current?.click()}>
                <FileUp /> Choose a CSV file
              </Button>
            </div>
            <Field label="Role for everyone without one of their own">
              {(p) => (
                <Select
                  {...p}
                  value={role}
                  onChange={(e) => {
                    const next = e.target.value as Role
                    setRole(next)
                    const parents = choicesFor(next, info.leads)
                    if (!parents.some((person) => person.id === manager)) setManager(parents[0]?.id ?? '')
                  }}
                >
                  {roles.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {chooseTeam && (
              <Field label="Reports to">
                {(p) => (
                  <Select {...p} value={manager} onChange={(e) => setManager(e.target.value)}>
                    <option value="">Not assigned yet</option>
                    {managerChoices.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name} ({l.role_display})
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            )}
            {text.trim() && (
              <div className="text-[13px]" role="status">
                <p>
                  {plural(parsed.rows.length, 'person', 'people')} read{parsed.problems.length > 0 ? `, ${parsed.problems.length} skipped:` : '.'}
                </p>
                {parsed.problems.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                    {parsed.problems.slice(0, 5).map((p) => (
                      <li key={p.line}>
                        Line {p.line}: {p.reason}
                      </li>
                    ))}
                    {parsed.problems.length > 5 && <li>and {parsed.problems.length - 5} more.</li>}
                  </ul>
                )}
              </div>
            )}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={invite.isPending} disabled={parsed.rows.length === 0}>
                {invite.isPending ? 'Creating…' : parsed.rows.length ? `Create ${plural(parsed.rows.length, 'invitation')}` : 'Create invitations'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
