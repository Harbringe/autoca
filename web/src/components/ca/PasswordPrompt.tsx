// Asking for the password of a locked PDF.
//
// The password opens that one file, once. It is held in this form only while it is typed, sent with the upload, and cleared as soon as
// it is sent. It is not remembered between files, not put in the address, and the file is kept on the server exactly as it was sent,
// still locked. A wrong password says so and asks again; it does not say "damaged".

import { Lock } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'

/** True for the two answers that mean "this PDF needs a password": none given, or the one given did not fit. */
export const isLockedCode = (code: string | undefined): code is 'password_required' | 'password_incorrect' =>
  code === 'password_required' || code === 'password_incorrect'

export function PasswordForm({
  fileName,
  wrong,
  busy,
  onSubmit,
  onCancel,
}: {
  fileName: string
  /** The last password did not open it. */
  wrong: boolean
  busy?: boolean
  onSubmit: (password: string) => void
  onCancel: () => void
}) {
  const [password, setPassword] = useState('')
  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!password) return
    const given = password
    setPassword('') // gone from this form the moment it is sent
    onSubmit(given)
  }
  return (
    <form onSubmit={submit} className="grid gap-3">
      <div className="flex gap-2 text-sm">
        <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <p>
          <span className="font-medium">{fileName}</span> is password-protected. Banks usually lock emailed statements with a password they
          have told you (often a date of birth or part of the account or phone number).
        </p>
      </div>
      <Field label="Password" error={wrong ? 'That password did not open the file. Check it and try again.' : undefined}>
        {(props) => (
          <Input
            {...props}
            type="password"
            autoComplete="off"
            autoFocus
            spellCheck={false}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      <p className="text-xs text-muted-foreground">
        It is used once, to read this file. It is not saved. The file itself is kept exactly as you sent it, still locked.
      </p>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={!password || busy}>{busy ? 'Opening…' : 'Open and read'}</Button>
      </div>
    </form>
  )
}

export function PasswordDialog(props: React.ComponentProps<typeof PasswordForm>) {
  return (
    <Dialog open onOpenChange={(open) => !open && props.onCancel()}>
      <DialogContent aria-describedby={undefined} className="max-w-md">
        <DialogHeader>
          <DialogTitle>This file is locked</DialogTitle>
          <DialogDescription>Enter its password to read it.</DialogDescription>
        </DialogHeader>
        <PasswordForm {...props} />
      </DialogContent>
    </Dialog>
  )
}
