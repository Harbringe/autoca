import { createFileRoute } from '@tanstack/react-router'
import { SoonScreen } from '@/features/soon/SoonScreen'

export const Route = createFileRoute('/_app/soon/$module')({ component: Screen })

function Screen() {
  return <SoonScreen module={Route.useParams().module} />
}
