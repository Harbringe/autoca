import { createFileRoute } from '@tanstack/react-router'
import { ClientOverview } from '@/features/clients/ClientOverview'

export const Route = createFileRoute('/_app/clients/$clientId/bookkeeping')({ component: BooksOverview })

function BooksOverview() {
  const { clientId } = Route.useParams()
  return <ClientOverview clientId={clientId} />
}
