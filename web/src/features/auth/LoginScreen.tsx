import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { messageOf } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { useSession } from '@/session/session'
import { AuthLayout } from './AuthLayout'

/** A sign-in that has heard nothing for this long is treated as a lost connection. */
const SIGN_IN_TIMEOUT_MS = 15_000

export function LoginScreen() {
  const { signIn } = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const passwordRef = useRef<HTMLInputElement>(null)
  const login = useMutation({
    // Without this the query library parks a mutation while the browser is offline, and the button
    // says "Signing in…" for ever. The attempt must run, fail, and say so.
    networkMode: 'always',
    mutationFn: async () => {
      const controller = new AbortController()
      let timer: ReturnType<typeof setTimeout> | undefined
      // The abort cancels the login request itself, but a server that never answers can also stall the
      // steps around it (the token fetch, reading who signed in), so the whole attempt is raced too.
      // A TypeError is how messageOf says "could not reach the server".
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          controller.abort()
          reject(new TypeError('Sign-in timed out'))
        }, SIGN_IN_TIMEOUT_MS)
      })
      try {
        return await Promise.race([signIn(email.trim(), password, controller.signal), timeout])
      } catch (error) {
        if (controller.signal.aborted) throw new TypeError('Sign-in timed out')
        throw error
      } finally {
        clearTimeout(timer)
      }
    },
  })
  // The password is what is retyped after a failed attempt, so the cursor goes there.
  useEffect(() => {
    if (login.isError) passwordRef.current?.focus()
  }, [login.isError, login.failureCount])

  function submit(event: FormEvent) {
    event.preventDefault()
    if (email && password) login.mutate()
  }

  return (
    <AuthLayout title="Sign in" subtitle="Use the email your firm invited you with.">
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <Field label="Email">
          {(props) => (
            <Input
              {...props}
              type="email"
              autoComplete="username"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          )}
        </Field>
        <Field label="Password">
          {(props) => (
            <Input
              {...props}
              ref={passwordRef}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        {login.error && (
          <p role="alert" className="text-sm text-destructive">
            {messageOf(login.error)}
          </p>
        )}
        <Button type="submit" size="lg" disabled={login.isPending || !email || !password}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthLayout>
  )
}
