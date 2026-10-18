// "Fetch GSTR-2B from the GST portal" on a run: one click when the taxpayer is signed in, else a short sign-in
// (portal username, then the OTP the portal sends them). The password is never asked for.

import { useQuery } from '@tanstack/react-query'
import { CloudDownload } from 'lucide-react'
import { useState } from 'react'
import { isApiError, messageOf } from '@/api/errors'
import { gstRegistrations, usePortalActions } from '@/api/queries/gst'
import type { GstReport } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { toast } from '@/lib/toast'

const wordsOf = (e: unknown) => (isApiError(e) ? messageOf(e) : 'Something went wrong. Try again.')

export function PortalFetch({
  clientId,
  report,
  variant,
  disabled,
  onFetched,
}: {
  clientId: string
  report: GstReport
  variant: 'primary' | 'secondary'
  disabled?: boolean
  onFetched: () => void
}) {
  const registrations = useQuery(gstRegistrations(clientId))
  const reg = registrations.data?.find((r) => r.gstin === report.registration.gstin)
  const actions = usePortalActions(clientId)
  const [signingIn, setSigningIn] = useState(false)
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState('')

  async function fetchNow() {
    setError('')
    setFetching(true)
    try {
      await actions.fetch.mutateAsync(report.id)
      toast.success('GSTR-2B fetched from the GST portal')
      onFetched()
    } catch (e) {
      setError(wordsOf(e))
    } finally {
      setFetching(false)
    }
  }

  if (!reg) return null
  return (
    <>
      <Button variant={variant} size="sm" loading={fetching} disabled={disabled} onClick={() => (reg.portal_connected ? void fetchNow() : setSigningIn(true))}>
        <CloudDownload /> Fetch from the GST portal
      </Button>
      {error && (
        <p role="alert" className="basis-full text-sm text-destructive sm:text-right">
          {error}
        </p>
      )}
      {signingIn && (
        <SignIn
          clientId={clientId}
          registrationId={reg.id}
          gstin={reg.gstin}
          username={reg.portal_username}
          onClose={() => setSigningIn(false)}
          onConnected={() => {
            setSigningIn(false)
            void fetchNow()
          }}
        />
      )}
    </>
  )
}

function SignIn({
  clientId,
  registrationId,
  gstin,
  username: known,
  onClose,
  onConnected,
}: {
  clientId: string
  registrationId: string
  gstin: string
  username: string
  onClose: () => void
  onConnected: () => void
}) {
  const actions = usePortalActions(clientId)
  const [username, setUsername] = useState(known)
  const [otp, setOtp] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const busy = actions.sendOtp.isPending || actions.connect.isPending

  async function send() {
    setError('')
    try {
      await actions.sendOtp.mutateAsync({ id: registrationId, username: username.trim() })
      setSent(true)
    } catch (e) {
      setError(wordsOf(e))
    }
  }

  async function connect() {
    setError('')
    try {
      await actions.connect.mutateAsync({ id: registrationId, username: username.trim(), otp: otp.trim() })
      onConnected()
    } catch (e) {
      setError(wordsOf(e))
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Connect {gstin} to the GST portal</DialogTitle>
          <DialogDescription>
            The taxpayer must have switched on API access on the portal (View Profile, Manage API Access). We send no password: the portal texts
            the taxpayer an OTP, and the session then lasts some hours.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field label="GST portal username">
            {(p) => <Input {...p} autoFocus autoComplete="off" value={username} disabled={sent} onChange={(e) => setUsername(e.target.value)} />}
          </Field>
          {sent && (
            <Field label="OTP from the portal" hint="Sent to the taxpayer’s registered mobile or email.">
              {(p) => <Input {...p} autoFocus inputMode="numeric" autoComplete="one-time-code" maxLength={8} className="font-mono" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))} />}
            </Field>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          {sent ? (
            <Button loading={actions.connect.isPending} disabled={otp.length < 4} onClick={() => void connect()}>
              Connect and fetch
            </Button>
          ) : (
            <Button loading={actions.sendOtp.isPending} disabled={!username.trim()} onClick={() => void send()}>
              Send OTP
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
