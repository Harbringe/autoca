import { createFileRoute } from '@tanstack/react-router'
import { ClientPipeline } from '@/features/work/ClientPipeline'

export const Route = createFileRoute('/_app/clients/$clientId/pipeline')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <ClientPipeline clientId={clientId} />
}
