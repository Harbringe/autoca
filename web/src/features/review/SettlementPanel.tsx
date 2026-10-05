// A payment on a supplier's or customer's own account, waiting in the review queue: which of their bills does it pay?
//
// The bank row says money moved to or from this party and nothing about which invoices it clears, so nothing is posted until
// a person says. The editor lists the party's open bills with an amount against each, prefilled from the server's suggestion;
// posting sends the decision with the approval, and the server re-checks it all.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { rowSettlement } from '@/api/queries/bills'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import type { Decision } from '@/lib/settlement'
import { SettlementEditor } from './SettlementEditor'

export function SettlementPanel({ clientId, row, onDone }: { clientId: string; row: Classification; onDone: () => void }) {
  const context = useQuery(rowSettlement(clientId, row.id))
  const invalidate = useInvalidateClient(clientId)
  const [busy, setBusy] = useState(false)

  if (context.isPending) return <p className="text-sm text-muted-foreground">Looking up {row.party_name ?? 'the party'}’s open bills…</p>
  if (context.isError) return <p role="alert" className="text-sm text-destructive">{messageOf(context.error)}</p>

  async function postAndSettle(decision: Decision) {
    if (decision.problem) return
    setBusy(true)
    try {
      await raw.post(`${V1}/clients/${clientId}/approvals/`, {
        classifications: [row.id],
        settlements: [{ classification: row.id, allocations: decision.allocations, remainder: decision.remainder }],
      })
      await invalidate()
      toast.success('Posted, and the bills are settled')
      onDone()
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return <SettlementEditor context={context.data} busy={busy} confirmLabel="Post and settle" onSubmit={(d) => void postAndSettle(d)} />
}
