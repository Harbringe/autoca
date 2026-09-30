import { createFileRoute } from '@tanstack/react-router'
import { MastersScreen, type MasterTab } from '@/features/masters/MastersScreen'

const TABS: MasterTab[] = ['parties', 'rules']

export const Route = createFileRoute('/_app/clients/$clientId/masters')({
  validateSearch: (search: Record<string, unknown>): { tab?: MasterTab } => ({
    tab: TABS.includes(search.tab as MasterTab) ? (search.tab as MasterTab) : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { tab } = Route.useSearch()
  return <MastersScreen clientId={clientId} tab={tab ?? 'parties'} />
}
