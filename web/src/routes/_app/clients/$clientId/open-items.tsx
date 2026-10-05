import { createFileRoute } from '@tanstack/react-router'
import { OpenItemsScreen } from '@/features/openitems/OpenItemsScreen'

export const Route = createFileRoute('/_app/clients/$clientId/open-items')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <OpenItemsScreen clientId={clientId} />
}
