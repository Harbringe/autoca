import { createFileRoute } from '@tanstack/react-router'
import { BillPrint } from '@/features/print/BillPrint'
import { ChequePrint } from '@/features/print/ChequePrint'
import { LedgerPrint } from '@/features/print/LedgerPrint'
import { VoucherPrint } from '@/features/print/VoucherPrint'

export const Route = createFileRoute('/_app/clients/$clientId/print')({
  // `bill` is the id of an invoice to print, `entry` of a voucher, `ledger` of a ledger statement.
  validateSearch: (search: Record<string, unknown>): { bill?: string; entry?: string; ledger?: string; cheque?: string } => ({
    bill: typeof search.bill === 'string' ? search.bill : undefined,
    entry: typeof search.entry === 'string' ? search.entry : undefined,
    ledger: typeof search.ledger === 'string' ? search.ledger : undefined,
    cheque: typeof search.cheque === 'string' ? search.cheque : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { bill, entry, ledger, cheque } = Route.useSearch()
  if (bill) return <BillPrint clientId={clientId} billId={bill} />
  if (cheque) return <ChequePrint clientId={clientId} chequeId={cheque} />
  if (ledger) return <LedgerPrint clientId={clientId} ledgerId={ledger} />
  return entry ? <VoucherPrint clientId={clientId} entryId={entry} /> : <p className="p-6 text-sm text-muted-foreground">Nothing to print.</p>
}
