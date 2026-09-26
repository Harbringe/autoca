import { createFileRoute } from '@tanstack/react-router'
import { StatementsScreen } from '@/features/statements/StatementsScreen'

export const Route = createFileRoute('/_app/clients/$clientId/statements')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <StatementsScreen clientId={clientId} />
}
