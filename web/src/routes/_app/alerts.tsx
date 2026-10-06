import { createFileRoute } from '@tanstack/react-router'
import { AlertsScreen, parseAlertsSearch } from '@/features/alerts/AlertsScreen'

export const Route = createFileRoute('/_app/alerts')({
  validateSearch: parseAlertsSearch,
  component: Screen,
})

function Screen() {
  return <AlertsScreen search={Route.useSearch()} />
}
