import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { messageOf } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { useSession } from '@/session/session'
import { AuthLayout } from './AuthLayout'

export function LoginScreen() {
  const { signIn } = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({ mutationFn: () => signIn(email.trim(), password) })

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
