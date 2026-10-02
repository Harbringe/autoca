// The product's map: which module a path belongs to, and where a client switch should land.
//
// The active sidebar item and the tab row are derived from the address, never stored, so any URL
// reproduces the view. These are pure functions of a pathname so they can be tested without a router.

export type ModuleId =
  | 'dashboard'
  | 'clients'
  | 'pipeline'
  | 'documents'
  | 'bookkeeping'
  | 'bank'
  | 'gst'
  | 'taxation'
  | 'audit'
  | 'compliance'
  | 'reports'
  | 'ai'
  | 'analytics'
  | 'staff'
  | 'notifications'
  | 'settings'

/** The client-scoped screens and the module each one belongs to. */
export const CLIENT_SCREEN_MODULE: Record<string, ModuleId> = {
  documents: 'documents',
  statements: 'bank',
  review: 'bank',
  bookkeeping: 'bookkeeping',
  daybook: 'bookkeeping',
  ledgers: 'bookkeeping',
  masters: 'bookkeeping',
  books: 'bookkeeping',
  reports: 'reports',
  gst: 'gst',
  team: 'clients',
}

/** Where a module opens for one client, and for the whole firm. */
export const MODULE_CLIENT_SCREEN: Partial<Record<ModuleId, string>> = {
  documents: 'documents',
  bank: 'statements',
  bookkeeping: 'bookkeeping',
  reports: 'reports',
  gst: 'gst',
}

export const FIRM_LANDING: Partial<Record<ModuleId, string>> = {
  documents: '/documents',
  bank: '/bank',
  bookkeeping: '/bookkeeping',
  reports: '/reports',
  gst: '/gst',
}

/** Modules that have no screen yet; each has a page at /soon/<slug>. */
export const SOON_MODULES = ['taxation', 'audit', 'compliance', 'ai', 'analytics', 'notifications'] as const
export type SoonModule = (typeof SOON_MODULES)[number]

const SEGMENT_MODULE: Record<string, ModuleId> = {
  dashboard: 'dashboard',
  documents: 'documents',
  clients: 'clients',
  pipeline: 'pipeline',
  bookkeeping: 'bookkeeping',
  bank: 'bank',
  gst: 'gst',
  reports: 'reports',
  staff: 'staff',
  settings: 'settings',
}

const segments = (pathname: string) => pathname.split('?')[0]!.split('/').filter(Boolean)

/** The module a path belongs to, or undefined for a path outside the app map. */
export function moduleOf(pathname: string): ModuleId | undefined {
  const [first, second, third] = segments(pathname)
  if (!first) return undefined
  if (first === 'soon') return (SOON_MODULES as readonly string[]).includes(second ?? '') ? (second as ModuleId) : undefined
  if (first === 'clients') {
    if (!second) return 'clients'
    return third ? (CLIENT_SCREEN_MODULE[third] ?? 'clients') : 'clients'
  }
  return SEGMENT_MODULE[first]
}

/** Which client the address is inside, if any. */
export function clientIdOf(pathname: string): string | undefined {
  const [first, second] = segments(pathname)
  return first === 'clients' ? second : undefined
}

/**
 * Where picking a client (or "All clients", `null`) should go, keeping the module and the tab:
 * /clients/A/daybook -> /clients/B/daybook; /bookkeeping -> /clients/B/daybook; anything not tied to a
 * module (the client list, settings) -> the client's profile. "All clients" from a client screen goes
 * to that module's firm landing, or to the client list.
 */
export function switchClientPath(pathname: string, clientId: string | null): string {
  const parts = segments(pathname)
  const module = moduleOf(pathname)
  if (clientId === null) {
    return (module && FIRM_LANDING[module]) || '/clients'
  }
  if (parts[0] === 'clients' && parts[1] && parts[2]) return `/clients/${clientId}/${parts[2]}`
  const screen = module && MODULE_CLIENT_SCREEN[module]
  if (screen && FIRM_LANDING[module] === `/${parts[0]}`) return `/clients/${clientId}/${screen}`
  return `/clients/${clientId}`
}
