import { createFileRoute } from '@tanstack/react-router'
import { useFy } from '@/features/shell/useFy'
import { TallyImportScreen } from '@/features/tally/TallyImportScreen'

export const Route = createFileRoute('/_app/clients/$clientId/tally')({
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { fy } = useFy()
  return <TallyImportScreen clientId={clientId} fy={fy} />
}
