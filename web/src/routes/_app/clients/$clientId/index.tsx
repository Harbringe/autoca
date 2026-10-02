import { createFileRoute } from '@tanstack/react-router'
import { ClientProfileScreen } from '@/features/clients/ClientProfileScreen'

export const Route = createFileRoute('/_app/clients/$clientId/')({ component: Overview })

function Overview() {
  const { clientId } = Route.useParams()
  return <ClientProfileScreen clientId={clientId} />
}
