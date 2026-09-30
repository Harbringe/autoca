import { createFileRoute } from '@tanstack/react-router'
import { MastersScreen } from '@/features/masters/MastersScreen'

export const Route = createFileRoute('/_app/clients/$clientId/ledgers')({
  component: LedgersRoute,
})

function LedgersRoute() {
  const { clientId } = Route.useParams()
  return <MastersScreen clientId={clientId} tab="ledgers" />
}
