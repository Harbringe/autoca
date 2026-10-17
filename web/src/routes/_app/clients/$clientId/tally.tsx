import { createFileRoute } from '@tanstack/react-router'
import { TallyImportScreen } from '@/features/tally/TallyImportScreen'

export const Route = createFileRoute('/_app/clients/$clientId/tally')({
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  return <TallyImportScreen clientId={clientId} />
}
