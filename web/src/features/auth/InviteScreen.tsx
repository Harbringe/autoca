import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { raw, resetCsrf } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import type { InviteDescription } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useSession } from '@/session/session'
import { AuthLayout } from './AuthLayout'

/** Opened from the link in an invitation, before there is a session to speak of. */
export function InviteScreen({ token }: { token: string }) {
  const { refresh } = useSession()
  const navigate = useNavigate()
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')

  const invite = useQuery({
    queryKey: ['invite', token],
    queryFn: () => raw.get<InviteDescription>('/auth/invite/', { token }),
    retry: false,
  })

  const accept = useMutation({
    mutationFn: () =>
      raw.post('/auth/invite/', { token, password, ...(invite.data?.has_account ? {} : { full_name: fullName.trim() }) }),
    onSuccess: async () => {
      resetCsrf()
      await refresh()
      await navigate({ to: '/', replace: true })
    },
  })

  if (invite.isPending) return <Spinner label="Opening your invitation…" className="min-h-svh" />
  if (invite.error) {
    return (
      <AuthLayout
        title="This invitation can't be used"
        subtitle={isApiError(invite.error) && invite.error.status === 410 ? invite.error.message : messageOf(invite.error)}
      >
        <p className="text-sm text-muted-foreground">Ask whoever invited you to send a new one.</p>
      </AuthLayout>
    )
  }

  const info = invite.data
  const canSubmit = password.length > 0 && (info.has_account || fullName.trim().length > 0)
  function submit(event: FormEvent) {
    event.preventDefault()
    if (canSubmit) accept.mutate()
  }
  const passwordError = isApiError(accept.error) ? accept.error.field('password') : undefined

  return (
    <AuthLayout
      title={`Join ${info.firm}`}
      subtitle={`You've been invited as ${info.role_display}${info.team ? ` on ${info.team}'s team` : ''}.`}
    >
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <Field label="Email">{(props) => <Input {...props} value={info.email} readOnly disabled />}</Field>
        {!info.has_account && (
          <Field label="Your name">
            {(props) => (
              <Input {...props} autoComplete="name" autoFocus value={fullName} onChange={(e) => setFullName(e.target.value)} />
            )}
          </Field>
        )}
        <Field
          label={info.has_account ? 'Your existing password' : 'Choose a password'}
          hint={info.has_account ? 'You already have an account, so use its password.' : 'At least 12 characters. A phrase is easiest to remember.'}
          error={passwordError}
        >
          {(props) => (
            <Input
              {...props}
              type="password"
              autoComplete={info.has_account ? 'current-password' : 'new-password'}
              autoFocus={info.has_account}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        {accept.error && !passwordError && (
          <p role="alert" className="text-sm text-destructive">
            {messageOf(accept.error)}
          </p>
        )}
        <Button type="submit" size="lg" disabled={accept.isPending || !canSubmit}>
          {accept.isPending ? 'Joining…' : 'Accept invitation'}
        </Button>
      </form>
    </AuthLayout>
  )
}
