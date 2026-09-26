import { createFileRoute } from '@tanstack/react-router'
import { ClientOverview } from '@/features/clients/ClientOverview'

export const Route = createFileRoute('/_app/clients/$clientId/')({ component: Overview })

function Overview() {
  const { clientId } = Route.useParams()
  return <ClientOverview clientId={clientId} />
}
