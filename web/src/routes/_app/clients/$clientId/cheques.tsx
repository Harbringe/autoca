import { createFileRoute } from '@tanstack/react-router'
import { ChequesScreen } from '@/features/cheques/ChequesScreen'
import { useSession } from '@/session/session'

export const Route = createFileRoute('/_app/clients/$clientId/cheques')({
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { can } = useSession()
  return <ChequesScreen clientId={clientId} mayEdit={can('journal.approve')} />
}
