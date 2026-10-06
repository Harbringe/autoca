import { createFileRoute } from '@tanstack/react-router'
import { AssetsScreen } from '@/features/assets/AssetsScreen'

export const Route = createFileRoute('/_app/clients/$clientId/assets')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <AssetsScreen clientId={clientId} />
}
