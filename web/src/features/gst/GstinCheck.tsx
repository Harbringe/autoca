// "Check with the GST portal" for a party's GSTIN: what the portal says beside what the books have.
// It informs and offers one click to take the portal's name into the form; nothing is saved by it.

import { ShieldCheck } from 'lucide-react'
import { isApiError, messageOf } from '@/api/errors'
import { useGstinCheck } from '@/api/queries/gst'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDateTime } from '@/lib/format'

const text = (v: unknown) => (typeof v === 'string' ? v : '')

export function GstinCheckPanel({
  clientId,
  partyId,
  bookName,
  onUseName,
}: {
  clientId: string
  partyId: string
  /** The name as it stands in the form, so a name changed there is compared as typed. */
  bookName: string
  onUseName: (name: string) => void
}) {
  const check = useGstinCheck(clientId)
  const result = check.data
  const run = (refresh: boolean) => check.mutate({ party: partyId, refresh })

  const rows: [string, string, string][] = result
    ? [
        ['Legal name', text(result.details.legal_name), bookName],
        ['Trade name', text(result.details.trade_name), ''],
        ['Status', result.status || '—', ''],
        ['Registration type', text(result.details.registration_type), ''],
        ['State', text(result.details.state), ''],
        ['Address', [text(result.details.address), text(result.details.pincode)].filter(Boolean).join(' '), ''],
      ]
    : []

  return (
    <div className="grid gap-2 rounded-md border border-[var(--faint)] p-3 sm:col-span-2" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={() => run(false)} disabled={check.isPending}>
          <ShieldCheck /> {check.isPending ? 'Checking…' : 'Check with the GST portal'}
        </Button>
        {result && result.outcome === 'found' && (
          <Badge tone={result.cancelled ? 'danger' : 'success'}>{result.cancelled ? `GSTIN ${result.status}` : 'Active on the portal'}</Badge>
        )}
        {result && result.outcome === 'found' && result.name_matches === false && <Badge tone="warning">Name differs</Badge>}
        {result && result.outcome === 'not_found' && <Badge tone="danger">Not on the portal</Badge>}
      </div>

      {check.isError && <p className="text-sm text-destructive">{isApiError(check.error) ? messageOf(check.error) : 'Could not check just now.'}</p>}
      {result?.message && <p className="text-sm text-muted-foreground">{result.message}</p>}

      {result && result.outcome === 'found' && (
        <>
          <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]">
            {rows
              .filter(([, portal]) => portal)
              .map(([label, portal]) => (
                <div key={label} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="break-words text-heading">{portal}</dd>
                </div>
              ))}
          </dl>
          <p className="text-xs text-muted-foreground">
            {result.from_cache ? 'Earlier answer' : 'Checked'} {result.checked_at ? formatDateTime(result.checked_at) : ''}
            {result.provider ? ` · ${result.provider}` : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            {text(result.details.legal_name) && result.name_matches === false && (
              <Button type="button" variant="outline" size="sm" onClick={() => onUseName(text(result.details.legal_name))}>
                Use the portal’s legal name in the form
              </Button>
            )}
            {result.from_cache && (
              <Button type="button" variant="ghost" size="sm" onClick={() => run(true)} disabled={check.isPending}>
                Ask the portal again
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
