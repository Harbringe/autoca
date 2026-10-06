// The slim rail: the firm's few places, always the same whichever page you are on. Nothing here
// depends on a client; the client's own screens are in lib/clientNav.ts. Pure data so it can be tested.

import type { ModuleId } from './modules'

export interface RailItem {
  id: Extract<ModuleId, 'dashboard' | 'clients' | 'pipeline' | 'alerts' | 'staff' | 'settings'>
  /** Under the icon on the rail. */
  label: string
  /** In the phone drawer, where there is room. */
  long: string
  /** Shown only to people holding this permission. */
  permission?: string
}

export const RAIL_ITEMS: RailItem[] = [
  { id: 'dashboard', label: 'Home', long: 'Dashboard', permission: 'client.view' },
  { id: 'clients', label: 'Clients', long: 'Clients', permission: 'client.view' },
  { id: 'pipeline', label: 'Pipeline', long: 'Work pipeline', permission: 'client.view' },
  { id: 'alerts', label: 'Alerts', long: 'Alerts', permission: 'client.view' },
  { id: 'staff', label: 'Staff', long: 'Staff performance', permission: 'client.view' },
  { id: 'settings', label: 'Settings', long: 'Settings' },
]

export function railItems(can: (permission: string) => boolean): RailItem[] {
  return RAIL_ITEMS.filter((i) => !i.permission || can(i.permission))
}

export function settingsHome(can: (permission: string) => boolean): string {
  return can('team.view') ? '/settings/team' : can('firm.manage') ? '/settings/firm' : '/settings/preferences'
}

export function railHref(item: RailItem, can: (permission: string) => boolean): string {
  switch (item.id) {
    case 'dashboard':
      return '/dashboard'
    case 'settings':
      return settingsHome(can)
    default:
      return `/${item.id}`
  }
}

/** The rail item the address is on. Only the firm's pages light one: inside a client the panel does the pointing. */
export function railActive(pathname: string): RailItem['id'] | undefined {
  const [first] = pathname.split('?')[0]!.split('/').filter(Boolean)
  if (first === 'clients') return pathname.split('?')[0]!.split('/').filter(Boolean).length === 1 ? 'clients' : undefined
  return RAIL_ITEMS.find((i) => i.id === first)?.id
}
