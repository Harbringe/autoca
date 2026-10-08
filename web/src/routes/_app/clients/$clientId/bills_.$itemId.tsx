import { createFileRoute } from '@tanstack/react-router'
import { ExpensePage } from '@/features/purchases/ExpensePage'
import type { VoucherKind } from '@/lib/vouchers'

const KINDS = ['PURCHASE', 'SALES', 'DEBIT_NOTE', 'CREDIT_NOTE']

export const Route = createFileRoute('/_app/clients/$clientId/bills_/$itemId')({
  // `as` says what the id is: an uploaded invoice, a bill with no file, or `new` for one keyed in.
  validateSearch: (search: Record<string, unknown>): { as: 'reading' | 'bill' | 'new'; kind?: VoucherKind } => ({
    as: search.as === 'bill' || search.as === 'new' ? search.as : 'reading',
    kind: typeof search.kind === 'string' && KINDS.includes(search.kind) ? (search.kind as VoucherKind) : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId, itemId } = Route.useParams()
  const { as, kind } = Route.useSearch()
  return <ExpensePage clientId={clientId} itemId={itemId} as={as} kind={kind} />
}
