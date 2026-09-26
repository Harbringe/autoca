import { useMutation, useQuery } from '@tanstack/react-query'
import QRCode from 'qrcode'
import { useState, type FormEvent } from 'react'
import { raw, resetCsrf } from '@/api/client'
import { messageOf } from '@/api/errors'
import type { MfaSetupResponse, MfaStep } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useSession } from '@/session/session'
import { AuthLayout } from './AuthLayout'

/** The secret inside an otpauth:// URI, for people who type it into their app instead of scanning. */
export function secretOf(uri: string): string {
  try {
    return new URL(uri).searchParams.get('secret') ?? ''
  } catch {
    return ''
  }
}

function groupSecret(secret: string): string {
  return secret.replace(/(.{4})/g, '$1 ').trim()
}

function SetupPanel() {
  // Provisioning is a POST, but asking twice just replaces the pending device, so it is
  // safe to treat as a query: the framework de-duplicates the double effect in development.
  const setup = useQuery({
    queryKey: ['mfa-setup'],
    queryFn: async () => {
      const { provisioningUri } = await raw.post<MfaSetupResponse>('/auth/mfa/setup/', {})
      const qr = await QRCode.toDataURL(provisioningUri, { margin: 1, width: 220, errorCorrectionLevel: 'M' })
      return { qr, secret: secretOf(provisioningUri) }
    },
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  })

  if (setup.isPending) return <Spinner label="Preparing your authenticator…" />
  if (setup.error) return <p role="alert" className="text-sm text-destructive">{messageOf(setup.error)}</p>

  return (
    <div className="mb-5 grid justify-items-center gap-3 rounded-md border bg-muted/40 p-4">
      <img src={setup.data.qr} alt="QR code to scan with your authenticator app" width={220} height={220} className="rounded bg-white" />
      <div className="text-center text-[13px] text-muted-foreground">
        Can&rsquo;t scan? Enter this key instead
        <div className="num mt-1 select-all font-mono text-sm tracking-wide text-foreground">{groupSecret(setup.data.secret)}</div>
      </div>
    </div>
  )
}

export function MfaScreen({ step }: { step: MfaStep }) {
  const { refresh, signOut } = useSession()
  const [token, setToken] = useState('')
  const verify = useMutation({
    mutationFn: () => raw.post('/auth/mfa/verify/', { token: token.trim() }),
    onSuccess: async () => {
      resetCsrf()
      await refresh()
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (token.trim().length >= 6) verify.mutate()
  }

  return (
    <AuthLayout
      title={step === 'setup' ? 'Set up your second factor' : 'Enter your code'}
      subtitle={
        step === 'setup'
          ? 'Scan the code with an authenticator app (Google Authenticator, Microsoft Authenticator, Authy), then enter the 6-digit code it shows.'
          : 'Open your authenticator app and enter the current 6-digit code.'
      }
    >
      {step === 'setup' && <SetupPanel />}
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <Field label="6-digit code">
          {(props) => (
            <Input
              {...props}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={8}
              autoFocus
              className="h-11 text-center font-mono text-lg tracking-[0.35em]"
              value={token}
              onChange={(e) => setToken(e.target.value.replace(/\D/g, ''))}
            />
          )}
        </Field>
        {verify.error && (
          <p role="alert" className="text-sm text-destructive">
            {messageOf(verify.error)}
          </p>
        )}
        <Button type="submit" size="lg" disabled={verify.isPending || token.length < 6}>
          {verify.isPending ? 'Checking…' : step === 'setup' ? 'Turn on and continue' : 'Verify'}
        </Button>
        <Button variant="link" size="sm" onClick={() => void signOut()}>
          Use a different account
        </Button>
      </form>
    </AuthLayout>
  )
}
