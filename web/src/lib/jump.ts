// The `g` + letter keys that jump between modules, and where each one lands.
//
// The sidebar, the palette and these keys all ask the same question ("where does this module open
// for whoever I am looking at?"), so it is answered once. With a client open a module opens that
// client's screen for it; under All clients it opens the module's firm landing.

import { FIRM_LANDING, MODULE_CLIENT_SCREEN, type ModuleId } from './modules'

export interface JumpKey {
  /** The second key; the first is always g. */
  key: string
  module: ModuleId
  label: string
  /** Offered only to people holding this permission. */
  permission: string
}

export const JUMP_KEYS: JumpKey[] = [
  { key: 'd', module: 'dashboard', label: 'Dashboard', permission: 'client.view' },
  { key: 'c', module: 'clients', label: 'Clients', permission: 'client.view' },
  { key: 'b', module: 'bookkeeping', label: 'Bookkeeping', permission: 'report.view' },
  { key: 's', module: 'bank', label: 'Bank statements', permission: 'transaction.view' },
  { key: 'r', module: 'reports', label: 'Reports', permission: 'report.view' },
  { key: 'g', module: 'gst', label: 'GST reconciliation', permission: 'gst.view' },
]

/** Where a module opens: the client's screen when a client is open, the firm landing otherwise. */
export function moduleHref(module: ModuleId, clientId?: string): string {
  if (module === 'dashboard') return '/dashboard'
  if (module === 'clients') return '/clients'
  const screen = MODULE_CLIENT_SCREEN[module]
  if (clientId && screen) return `/clients/${clientId}/${screen}`
  return FIRM_LANDING[module] ?? `/${module}`
}
