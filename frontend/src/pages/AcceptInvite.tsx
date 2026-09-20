import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useSession } from '../auth/session'
import { Button, ErrorNote, Field, Spinner } from '../components/ui'

interface InviteInfo {
  email: string
  full_name: string
  firm: string
  role_display: string
  team: string
  has_account: boolean
}

export default function AcceptInvite() {
  const { token = '' } = useParams()
  const { refresh } = useSession()
  const navigate = useNavigate()
  const [info, setInfo] = useState<InviteInfo | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.get<InviteInfo>(`/auth/invite/?token=${encodeURIComponent(token)}`).then(
      (result) => {
        setInfo(result)
        setName(result.full_name)
      },
      setLoadError,
    )
  }, [token])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!info) return
    if (!info.has_account && password !== confirm) {
      setError(new Error('The two passwords don’t match.'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.post('/auth/invite/', { token, full_name: name, password })
      await refresh()
      navigate('/', { replace: true })
    } catch (err) {
      setError(err)
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
        {loadError ? (
          <>
            <h1>Invite link</h1>
            <ErrorNote error={loadError instanceof ApiError ? loadError : 'This invite link isn’t valid.'} />
          </>
        ) : !info ? (
          <Spinner />
        ) : (
          <>
            <h1>Join {info.firm}</h1>
            <p className="sub">
              You've been invited as <strong>{info.role_display}</strong>
              {info.team ? ` on ${info.team}'s team` : ''}.
            </p>
            <ErrorNote error={error} />
            <Field label="Email">
              <input type="email" value={info.email} readOnly />
            </Field>
            {info.has_account ? (
              <Field label="Your AutoCA password" hint="You already have an account. Sign in to add this firm to it.">
                <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
              </Field>
            ) : (
              <>
                <Field label="Your name">
                  <input type="text" required value={name} onChange={(e) => setName(e.target.value)} autoFocus />
                </Field>
                <Field label="Choose a password" hint="At least 12 characters.">
                  <input type="password" autoComplete="new-password" required minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} />
                </Field>
                <Field label="Type it again">
                  <input type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                </Field>
              </>
            )}
            <p className="sub">Next you'll set up an authenticator app. It's required for everyone.</p>
            <Button kind="primary" type="submit" busy={busy}>
              Accept invite
            </Button>
          </>
        )}
      </form>
    </div>
  )
}
