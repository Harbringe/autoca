import { createFileRoute } from '@tanstack/react-router'
import { BillsScreen } from '@/features/bills/BillsScreen'

export const Route = createFileRoute('/_app/clients/$clientId/bills')({
  // `bill` opens one bill's detail on arrival: the Day Book links a voucher entry here, because a voucher is changed through its bill.
  validateSearch: (search: Record<string, unknown>): { bill?: string } => ({
    bill: typeof search.bill === 'string' && /^[0-9a-f-]{32,36}$/i.test(search.bill) ? search.bill : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { bill } = Route.useSearch()
  return <BillsScreen clientId={clientId} openId={bill} />
}
