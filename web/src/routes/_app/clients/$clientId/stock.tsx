import { createFileRoute } from '@tanstack/react-router'
import { StockItemsScreen } from '@/features/stock/StockItemsScreen'
import { useSession } from '@/session/session'

export const Route = createFileRoute('/_app/clients/$clientId/stock')({
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { can } = useSession()
  return <StockItemsScreen clientId={clientId} mayEdit={can('ledger.manage')} />
}
