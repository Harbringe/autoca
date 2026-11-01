import { createFileRoute } from '@tanstack/react-router'
import { BillPrint } from '@/features/print/BillPrint'

export const Route = createFileRoute('/_app/clients/$clientId/print')({
  // `bill` is the id of the invoice to print.
  validateSearch: (search: Record<string, unknown>): { bill?: string } => ({ bill: typeof search.bill === 'string' ? search.bill : undefined }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { bill } = Route.useSearch()
  return bill ? <BillPrint clientId={clientId} billId={bill} /> : <p className="p-6 text-sm text-muted-foreground">Nothing to print.</p>
}
