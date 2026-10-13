import { createFileRoute } from '@tanstack/react-router'
import { MastersScreen, type MasterTab } from '@/features/masters/MastersScreen'

/** The tabs this page has. Ledgers is its own page (`/clients/$clientId/ledgers`), so a `?tab=ledgers` here would only fall back to Parties. */
type MastersTab = Exclude<MasterTab, 'ledgers'>
const TABS: MastersTab[] = ['parties', 'rules']

export const Route = createFileRoute('/_app/clients/$clientId/masters')({
  validateSearch: (search: Record<string, unknown>): { tab?: MastersTab } => ({
    tab: TABS.includes(search.tab as MastersTab) ? (search.tab as MastersTab) : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { tab } = Route.useSearch()
  return <MastersScreen clientId={clientId} tab={tab ?? 'parties'} />
}
