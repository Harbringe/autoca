import { createFileRoute } from '@tanstack/react-router'
import { TdsScreen } from '@/features/tds/TdsScreen'

export const Route = createFileRoute('/_app/clients/$clientId/tds')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <TdsScreen clientId={clientId} />
}
