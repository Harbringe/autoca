// The second factor, driven entirely from the SPA against the JSON endpoints.
// Enrolment: ask the server for a provisioning URI, draw it as a QR code
// client-side, and prove one code before the device counts. Verification:
// one code.

import { useEffect, useState, type FormEvent } from 'react'
import QRCode from 'qrcode'
import { api } from '../api/client'
import { useSession } from '../auth/session'
import { Button, ErrorNote, Field } from '../components/ui'

export default function Mfa({ step }: { step: 'setup' | 'verify' }) {
  const { refresh, signOut } = useSession()
  const [uri, setUri] = useState<string>('')
  const [qr, setQr] = useState<string>('')
  const [token, setToken] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (step !== 'setup') return
    let live = true
    api
      .post<{ provisioningUri: string }>('/auth/mfa/setup/', {})
      .then(async ({ provisioningUri }) => {
        if (!live) return
        setUri(provisioningUri)
        setQr(await QRCode.toDataURL(provisioningUri, { margin: 1, width: 200 }))
      })
      .catch((err) => live && setError(err))
    return () => {
      live = false
    }
  }, [step])

  const secret = uri ? new URL(uri).searchParams.get('secret') ?? '' : ''

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/auth/mfa/verify/', { token: token.trim() })
      await refresh()
    } catch (err) {
      setError(err)
      setToken('')
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
        {step === 'setup' ? (
          <>
            <h1>Set up your authenticator</h1>
            <p className="sub">
              Scan this with Google Authenticator, Authy or any TOTP app, then enter the six-digit code it shows. Every account needs one; a password alone does not open anything.
            </p>
            <div className="qr">{qr ? <img src={qr} alt="QR code for your authenticator app" /> : <span className="sub">Preparing…</span>}</div>
            {secret && (
              <>
                <p className="sub">Or enter this key by hand:</p>
                <div className="secret">{secret.replace(/(.{4})/g, '$1 ').trim()}</div>
              </>
            )}
          </>
        ) : (
          <>
            <h1>Second factor</h1>
            <p className="sub">Enter the current code from your authenticator app.</p>
          </>
        )}
        <ErrorNote error={error} />
        <Field label="Six-digit code">
          <input
            className="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            value={token}
            onChange={(e) => setToken(e.target.value.replace(/\D/g, ''))}
            autoFocus
          />
        </Field>
        <div className="row between">
          <Button kind="ghost" onClick={() => void signOut()}>
            Use a different account
          </Button>
          <Button kind="primary" type="submit" busy={busy}>
            Verify
          </Button>
        </div>
      </form>
    </div>
  )
}
