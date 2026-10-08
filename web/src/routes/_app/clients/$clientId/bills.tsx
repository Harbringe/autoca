import { createFileRoute, redirect } from '@tanstack/react-router'
import { PurchasesScreen } from '@/features/purchases/PurchasesScreen'

export const Route = createFileRoute('/_app/clients/$clientId/bills')({
  // `bill` opens one bill on arrival: the Day Book links a voucher entry here, because a voucher is changed through its bill.
  validateSearch: (search: Record<string, unknown>): { bill?: string } => ({
    bill: typeof search.bill === 'string' && /^[0-9a-f-]{32,36}$/i.test(search.bill) ? search.bill : undefined,
  }),
  beforeLoad: ({ search, params }) => {
    if (search.bill) throw redirect({ to: '/clients/$clientId/bills/$itemId', params: { clientId: params.clientId, itemId: search.bill }, search: { as: 'bill' } })
  },
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  return <PurchasesScreen clientId={clientId} />
}
