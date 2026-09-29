import { createFileRoute } from '@tanstack/react-router'
import { ClientTeamScreen } from '@/features/clients/ClientTeamScreen'

export const Route = createFileRoute('/_app/clients/$clientId/team')({
  validateSearch: (search: Record<string, unknown>): { new?: true } => (search.new === true || search.new === 'true' || search.new === 1 ? { new: true } : {}),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { new: isNew } = Route.useSearch()
  return <ClientTeamScreen clientId={clientId} justCreated={!!isNew} />
}
