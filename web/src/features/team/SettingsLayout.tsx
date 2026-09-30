// Settings: the firm's own pages behind one tab row. Each tab is shown only to people who may use it.

import { Navigate, Outlet } from '@tanstack/react-router'
import { HeadingLevel } from '@/components/ca/Page'
import { TabNav, type TabItem } from '@/components/ui/tabs'
import { useSession } from '@/session/session'

export function SettingsLayout() {
  const { can } = useSession()
  const tabs: TabItem[] = [
    ...(can('team.view') ? [{ to: '/settings/team', label: 'Team & roles' }] : []),
    ...(can('firm.manage') ? [{ to: '/settings/firm', label: 'Firm' }] : []),
  ]
  return (
    <div className="grid gap-5">
      <h1 className="text-[26px] leading-8 xl:text-[28px] xl:leading-[34px]">Settings</h1>
      {tabs.length > 1 && <TabNav label="Settings sections" items={tabs} />}
      <HeadingLevel.Provider value={2}>
        <Outlet />
      </HeadingLevel.Provider>
    </div>
  )
}

/** /settings opens the first page the person may use. */
export function SettingsHome() {
  const { can } = useSession()
  if (can('team.view')) return <Navigate to="/settings/team" replace />
  if (can('firm.manage')) return <Navigate to="/settings/firm" replace />
  return <Navigate to="/clients" replace />
}
