import { createFileRoute } from '@tanstack/react-router'
import { DayBookScreen } from '@/features/daybook/DayBookScreen'

export const Route = createFileRoute('/_app/clients/$clientId/daybook')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <DayBookScreen clientId={clientId} />
}
