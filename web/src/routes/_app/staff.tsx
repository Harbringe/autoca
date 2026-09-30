import { createFileRoute } from '@tanstack/react-router'
import { parseWorkSearch, WorkScreen } from '@/features/work/WorkScreen'

export const Route = createFileRoute('/_app/staff')({
  validateSearch: parseWorkSearch,
  component: Screen,
})

function Screen() {
  return <WorkScreen search={Route.useSearch()} />
}
