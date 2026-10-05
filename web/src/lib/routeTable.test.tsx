import { createMemoryHistory, createRouter } from '@tanstack/react-router'
import { routeTree } from '@/routeTree.gen'
import { JUMP_KEYS, moduleHref } from './jump'
import { FIRM_LANDING, MODULE_CLIENT_SCREEN, SOON_MODULES, switchClientPath, type ModuleId } from './modules'
import { nextTarget } from './overview'

// Every address the app links to must be a screen of the route tree, not the not-found page. The
// links are collected from the same functions the sidebar, palette, jump keys, dashboard and the
// firm-level client tables use, plus the table of routes in the design spec (3.4).

const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: ['/'] }) })
const ID = 'c1'

function resolves(path: string): boolean {
  const pathname = path.split('?')[0]!
  const matches = router.matchRoutes(pathname, {})
  const last = matches[matches.length - 1]
  return !!last && last.routeId !== '/_app/$' && last.routeId !== '__root__' && !matches.some((m) => m.status === 'notFound')
}

const unresolved = (paths: string[]) => [...new Set(paths)].filter((p) => !resolves(p))

describe('route table', () => {
  it('has every route of spec 3.4', () => {
    expect(
      unresolved([
        '/', '/dashboard', '/clients', `/clients/${ID}`, `/clients/${ID}/statements`, `/clients/${ID}/review`,
        `/clients/${ID}/bookkeeping`, `/clients/${ID}/bills`, `/clients/${ID}/daybook`, `/clients/${ID}/ledgers`, `/clients/${ID}/masters`, `/clients/${ID}/books`,
        `/clients/${ID}/reports`, `/clients/${ID}/team`, `/clients/${ID}/gst`, '/pipeline', '/bookkeeping', '/bank',
        '/gst', '/reports', '/work', '/staff', '/team', '/firm', '/settings/team', '/settings/firm',
        '/settings/activity', '/settings/preferences', '/settings', '/soon/documents',
      ]),
    ).toEqual([])
  })

  it('does not treat a stray address as a screen', () => {
    expect(resolves('/nope-404')).toBe(false)
  })

  it('resolves every sidebar, jump-key and palette target, with and without a client', () => {
    const modules: ModuleId[] = ['dashboard', 'clients', 'pipeline', 'bookkeeping', 'bank', 'gst', 'reports', 'staff']
    const paths = [
      ...modules.flatMap((m) => [moduleHref(m), moduleHref(m, ID)]),
      ...JUMP_KEYS.flatMap((j) => [moduleHref(j.module), moduleHref(j.module, ID)]),
      ...SOON_MODULES.map((m) => `/soon/${m}`),
      ...Object.values(FIRM_LANDING),
      ...Object.values(MODULE_CLIENT_SCREEN).map((s) => `/clients/${ID}/${s}`),
    ]
    expect(unresolved(paths as string[])).toEqual([])
  })

  it('resolves where switching client lands, from every module', () => {
    const from = ['/clients', '/clients/a/daybook', '/clients/a', '/dashboard', '/bookkeeping', '/bank', '/reports', '/gst', '/pipeline', '/staff', '/settings/team']
    expect(unresolved(from.flatMap((p) => [switchClientPath(p, ID), switchClientPath(p, null)]))).toEqual([])
  })

  it('resolves where each next step of a client leads (dashboard, client tables, clients list)', () => {
    const codes = ['upload', 'place', 'post', 'send_for_review', 'sign_off', 'none'] as const
    const paths = codes.map((c) => nextTarget(c as never).to.replace('$clientId', ID))
    expect(unresolved(paths)).toEqual([])
  })
})
