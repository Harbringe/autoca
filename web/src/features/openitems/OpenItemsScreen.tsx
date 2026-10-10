// To fix: everything about this client's books that does not yet tie out, as one list, oldest first.
//
// Each kind of document registers what can be left unmatched about it, so the list grows with the app instead of becoming a
// report per document. Nothing here is stored: an item that has been fixed is simply no longer listed. Each row opens the
// place where it is fixed: a bill, a party's account, or a posted payment to settle or explain.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { entryMoveContext, entrySettlement, openItems, useMoveToParty, useSetBillStatus, useSettleEntry } from '@/api/queries/bills'
import type { OpenItem } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { PartyStatementDialog } from '@/features/bills/PartyStatementDialog'
import { SettlementEditor } from '@/features/review/SettlementEditor'
import { OpeningBillsDialog } from './OpeningBillsDialog'
import { plural } from '@/lib/format'
import { useSession } from '@/session/session'

type Why = 'NO_INVOICE_EXPECTED' | 'NEEDS_INVOICE'

export function OpenItemsScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const [kind, setKind] = useState('')
  const list = useQuery(openItems(clientId, kind))
  const [settling, setSettling] = useState<string | null>(null)
  const [statement, setStatement] = useState<string | null>(null)
  const [opening, setOpening] = useState<string | null>(null)
  const [moving, setMoving] = useState<string | null>(null)
  const setStatus = useSetBillStatus(clientId)
  const mayFix = can('journal.approve')

  if (list.isPending) return <Spinner label="Looking for what does not tie out…" />
  if (list.isError) return <ErrorState error={list.error} retry={() => void list.refetch()} />
  const { items, kinds, count } = list.data

  async function say(entry: string, status: Why) {
    try {
      await setStatus.mutateAsync({ entry, status })
      toast.success(status === 'NO_INVOICE_EXPECTED' ? 'Marked as a direct expense' : 'Kept as waiting for its invoice')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {count === 0 ? 'Everything ties out.' : `${plural(count, 'item')} to fix, oldest first.`} Fixing one removes it from this list.
        </p>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Show</span>
          <Select aria-label="Kind of item" className="w-64" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All ({count})</option>
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>{k.title} ({k.count})</option>
            ))}
          </Select>
        </label>
      </div>

      {items.length === 0 ? (
        <EmptyState title="Nothing to fix here">Every document is matched to the books for this view.</EmptyState>
      ) : (
        <ul className="grid gap-2">
          {items.map((item, i) => (
            <li key={`${item.kind}-${item.link?.id ?? i}-${i}`} className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-card p-3">
              <div className="min-w-0">
                <div className="text-xs font-medium text-muted-foreground">
                  {item.title}
                  {item.age_days != null && ` · ${plural(item.age_days, 'day')} old`}
                </div>
                <div className="text-sm">{item.summary}</div>
              </div>
              <div className="flex items-center gap-3">
                {item.amount_display && <Money display={item.amount_display} />}
                <Actions clientId={clientId} item={item} mayFix={mayFix} onSettle={setSettling} onStatement={setStatement} onOpening={setOpening} onMove={setMoving} onSay={(e, s) => void say(e, s)} />
              </div>
            </li>
          ))}
        </ul>
      )}

      {settling && <SettleDialog clientId={clientId} entryId={settling} onClose={() => setSettling(null)} />}
      {moving && <SettleDialog clientId={clientId} entryId={moving} mode="move" onClose={() => setMoving(null)} />}
      {opening && <OpeningBillsDialog clientId={clientId} partyId={opening} partyName="This party" onClose={() => setOpening(null)} />}
      {statement && <PartyStatementDialog clientId={clientId} partyId={statement} partyName="this party" onClose={() => setStatement(null)} />}
    </div>
  )
}

function Actions({
  clientId,
  item,
  mayFix,
  onSettle,
  onStatement,
  onOpening,
  onMove,
  onSay,
}: {
  clientId: string
  item: OpenItem
  mayFix: boolean
  onSettle: (entry: string) => void
  onStatement: (party: string) => void
  onOpening: (party: string) => void
  onMove: (entry: string) => void
  onSay: (entry: string, status: Why) => void
}) {
  if (item.kind === 'tds_not_deposited' || item.kind === 'tds_payment_without_challan') {
    return (
      <Button size="sm" asChild>
        <Link to="/clients/$clientId/tds" params={{ clientId }}>Open TDS</Link>
      </Button>
    )
  }
  if (item.kind === 'fixed_asset_unregistered') {
    return (
      <Button size="sm" asChild>
        <Link to="/clients/$clientId/assets" params={{ clientId }}>Open assets</Link>
      </Button>
    )
  }
  if (item.kind === 'client_gstin_missing') {
    return (
      <Button size="sm" asChild>
        <Link to="/clients/$clientId/gst" params={{ clientId }}>Add the GSTIN</Link>
      </Button>
    )
  }
  const link = item.link
  if (!link) return null
  if (link.type === 'bill') {
    return (
      <Button variant="outline" size="sm" asChild>
        <Link to="/clients/$clientId/bills" params={{ clientId }} search={{ bill: link.id }}>Open bill</Link>
      </Button>
    )
  }
  if (link.type === 'invoice') {
    return (
      <Button size="sm" asChild>
        <Link to="/clients/$clientId/invoices" params={{ clientId }}>Open invoices</Link>
      </Button>
    )
  }
  if (link.type === 'party' && item.kind === 'party_opening_unbilled') {
    return mayFix ? <Button size="sm" onClick={() => onOpening(link.id)}>Break into bills</Button> : null
  }
  if (link.type === 'party') {
    return <Button variant="outline" size="sm" onClick={() => onStatement(link.id)}>Open account</Button>
  }
  // A posted payment: settle it against bills, or say why it has no invoice.
  const bypass = ['payment_bypasses_bills', 'payment_needs_invoice', 'payment_without_invoice'].includes(item.kind)
  return (
    <div className="flex gap-2">
      {mayFix && !bypass && <Button size="sm" onClick={() => onSettle(link.id)}>Settle</Button>}
      {mayFix && bypass && (
        <>
          {item.kind === 'payment_bypasses_bills' && <Button size="sm" onClick={() => onMove(link.id)}>Move to the party’s account</Button>}
          <Button variant="outline" size="sm" onClick={() => onSay(link.id, 'NO_INVOICE_EXPECTED')}>No invoice expected</Button>
          {(item.kind === 'payment_bypasses_bills' || item.kind === 'payment_without_invoice') && (
            <Button variant="outline" size="sm" onClick={() => onSay(link.id, 'NEEDS_INVOICE')}>Waiting for invoice</Button>
          )}
        </>
      )}
      <Button variant="ghost" size="sm" asChild>
        <Link to="/clients/$clientId/daybook" params={{ clientId }}>Day Book</Link>
      </Button>
    </div>
  )
}

function SettleDialog({ clientId, entryId, mode = 'settle', onClose }: { clientId: string; entryId: string; mode?: 'settle' | 'move'; onClose: () => void }) {
  const moving = mode === 'move'
  const context = useQuery(moving ? entryMoveContext(clientId, entryId) : entrySettlement(clientId, entryId))
  const settleOnly = useSettleEntry(clientId)
  const move = useMoveToParty(clientId)
  const settle = moving ? move : settleOnly
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{moving ? 'Move a payment onto the party’s account' : 'Settle a payment'}</DialogTitle>
          <DialogDescription>
            {moving
              ? 'This payment was booked to a head, so its invoice would be counted twice. Moving it puts it on the party’s account against the bills you pick, so the bill shows as paid.'
              : 'Say which bills this posted payment clears. The rest is held on account or as an advance.'}
          </DialogDescription>
        </DialogHeader>
        {context.isPending ? (
          <Spinner label="Looking up the open bills…" />
        ) : context.isError ? (
          <ErrorState error={context.error} retry={() => void context.refetch()} />
        ) : (
          <SettlementEditor
            context={context.data}
            busy={settle.isPending}
            confirmLabel={moving ? 'Move and settle' : 'Settle'}
            onSubmit={(d) => {
              if (d.problem) return
              settle.mutate(
                { entry: entryId, allocations: d.allocations, remainder: d.remainder },
                {
                  onSuccess: () => {
                    toast.success(moving ? 'Moved onto the party’s account and settled' : 'Settled')
                    onClose()
                  },
                  onError: (e) => toast.error(messageOf(e)),
                },
              )
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
