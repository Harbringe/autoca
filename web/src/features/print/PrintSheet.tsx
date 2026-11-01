// A page laid out for paper: a toolbar that stays off the paper (Print, Back), and an A4 sheet that is all the printer sees.
// The firm's heading is the same on every printed document, so it lives here.

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { clientDetail } from '@/api/queries/clients'
import { gstRegistrations } from '@/api/queries/gst'
import { Button } from '@/components/ui/button'

export function PrintSheet({ clientId, title, children }: { clientId: string; title: string; children: ReactNode }) {
  const client = useQuery(clientDetail(clientId))
  const registrations = useQuery(gstRegistrations(clientId))
  const c = client.data as (typeof client.data & { trade_name?: string; address?: string; pan?: string }) | undefined
  const gstins = (registrations.data ?? []).map((r) => r.gstin).filter(Boolean)

  return (
    <div className="mx-auto grid max-w-[210mm] gap-3">
      <div className="no-print flex justify-end gap-2">
        <Button variant="outline" onClick={() => window.history.back()}>
          Back
        </Button>
        <Button onClick={() => window.print()}>Print</Button>
      </div>
      <article aria-label={title} className="print-sheet grid gap-4 rounded-xl border border-border-strong bg-white p-8 text-sm text-black">
        <header className="grid gap-0.5 border-b border-black pb-3">
          <h1 className="text-lg font-semibold">{c?.name ?? ''}</h1>
          {c?.address ? <p className="whitespace-pre-line">{c.address}</p> : null}
          {gstins.length > 0 && <p>GSTIN: {gstins.join(', ')}</p>}
          {c?.pan ? <p>PAN: {c.pan}</p> : null}
        </header>
        <h2 className="text-center text-base font-semibold uppercase tracking-wide">{title}</h2>
        {children}
      </article>
    </div>
  )
}
