import { createFileRoute } from '@tanstack/react-router'
import { Workspace } from '@/features/clients/Workspace'

export const Route = createFileRoute('/_app/clients/$clientId')({ component: ClientWorkspace })

function ClientWorkspace() {
  const { clientId } = Route.useParams()
  return <Workspace clientId={clientId} />
}
