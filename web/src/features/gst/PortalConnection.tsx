// A client's GST portal connection, per GSTIN, on the client profile: whether the taxpayer is signed in, who as, and
// until when. Connecting here means "Fetch from the GST portal" on a run is then one click while the session lasts.

import { useQuery } from '@tanstack/react-query'
import { Plug } from 'lucide-react'
import { useState } from 'react'
import { isApiError, messageOf } from '@/api/errors'
import { gstRegistrations, usePortalActions } from '@/api/queries/gst'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDateTime } from '@/lib/format'
import { toast } from '@/lib/toast'
import { useSession } from '@/session/session'
import { SignIn } from './PortalFetch'

export function PortalConnection({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const registrations = useQuery(gstRegistrations(clientId))
  const actions = usePortalActions(clientId)
  const [signingIn, setSigningIn] = useState<string | null>(null)
  const [error, setError] = useState('')
  const list = registrations.data ?? []
  if (list.length === 0) return null
  const canPrepare = can('gst.prepare')

  async function disconnect(id: string) {
    setError('')
    try {
      await actions.disconnect.mutateAsync(id)
      toast.success('Disconnected from the GST portal')
    } catch (e) {
      setError(isApiError(e) ? messageOf(e) : 'Could not disconnect. Try again.')
    }
  }

  const target = list.find((r) => r.id === signingIn)
  return (
    <div className="sm:col-span-2">
      <dt className="text-sm text-muted-foreground">GST portal connection</dt>
      <dd className="mt-1 grid gap-2">
        {list.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="num text-base font-semibold text-heading">{r.gstin}</span>
            {r.portal_connected ? (
              <>
                <Badge tone="success">Connected</Badge>
                <span className="text-sm font-normal text-muted-foreground">
                  {r.portal_username}
                  {r.portal_session_expires ? ` · until ${formatDateTime(r.portal_session_expires)}` : ''}
                </span>
              </>
            ) : (
              <span className="text-sm font-normal text-muted-foreground">Not connected{r.portal_username ? ` · last used ${r.portal_username}` : ''}</span>
            )}
            {canPrepare && (
              <>
                <Button size="sm" variant="secondary" onClick={() => setSigningIn(r.id)}>
                  <Plug /> {r.portal_connected ? 'Reconnect' : 'Connect'}
                </Button>
                {r.portal_connected && (
                  <Button size="sm" variant="ghost" loading={actions.disconnect.isPending} onClick={() => void disconnect(r.id)}>
                    Disconnect
                  </Button>
                )}
              </>
            )}
          </div>
        ))}
        {error && (
          <p role="alert" className="text-sm font-normal text-destructive">
            {error}
          </p>
        )}
        <p className="text-xs font-normal text-muted-foreground">
          The taxpayer switches on API access on the GST portal (View Profile, Manage API Access). We never ask for the portal password: the portal
          sends the taxpayer an OTP, and the session lasts some hours.
        </p>
      </dd>
      {target && (
        <SignIn
          clientId={clientId}
          registrationId={target.id}
          gstin={target.gstin}
          username={target.portal_username}
          confirmLabel="Connect"
          onClose={() => setSigningIn(null)}
          onConnected={() => {
            setSigningIn(null)
            toast.success('Connected to the GST portal')
          }}
        />
      )}
    </div>
  )
}
