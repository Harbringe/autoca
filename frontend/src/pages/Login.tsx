import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { useSession } from '../auth/session'
import { Button, ErrorNote, Field } from '../components/ui'

export default function Login() {
  const { setMfa } = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api.post<{ mfa: 'setup' | 'verify' }>('/auth/login/', { email, password })
      setMfa(result.mfa)
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? err : err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark">₹</span>
          <span>AutoCA</span>
        </div>
        <h1>Sign in</h1>
        <p className="sub">Your firm's bookkeeping workspace. A second factor is required after the password.</p>
        <ErrorNote error={error} />
        <Field label="Email">
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button kind="primary" type="submit" busy={busy}>
          Continue
        </Button>
      </form>
    </div>
  )
}
