import { createFileRoute } from '@tanstack/react-router'
import { DocumentsScreen } from '@/features/documents/DocumentsScreen'

export const Route = createFileRoute('/_app/clients/$clientId/documents')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <DocumentsScreen clientId={clientId} />
}
