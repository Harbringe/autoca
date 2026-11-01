import { createFileRoute } from '@tanstack/react-router'
import { AuditTrailScreen } from '@/features/books/AuditTrailScreen'

export const Route = createFileRoute('/_app/clients/$clientId/audit')({
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  return <AuditTrailScreen clientId={clientId} />
}
