import { RAIL_ITEMS, railActive, railHref, railItems, settingsHome } from './sidebarNav'

const only = (...held: string[]) => (p: string) => held.includes(p)

describe('the rail', () => {
  it('is the firm places, labelled, in a fixed order, with no coming-soon entries', () => {
    expect(railItems(() => true).map((i) => i.label)).toEqual(['Home', 'Clients', 'Pipeline', 'Alerts', 'Staff', 'Settings'])
    expect(RAIL_ITEMS.every((i) => i.label.length > 0)).toBe(true)
  })
  it('hides what the person may not see, but always keeps Settings', () => {
    expect(railItems(() => false).map((i) => i.id)).toEqual(['settings'])
    expect(railItems(only('client.view')).map((i) => i.id)).toEqual(['dashboard', 'clients', 'pipeline', 'alerts', 'staff', 'settings'])
  })
  it('sends Settings to the first page the person may use', () => {
    expect(settingsHome(only('team.view', 'firm.manage'))).toBe('/settings/team')
    expect(settingsHome(only('firm.manage'))).toBe('/settings/firm')
    expect(settingsHome(() => false)).toBe('/settings/preferences')
    const settings = RAIL_ITEMS.find((i) => i.id === 'settings')!
    expect(railHref(settings, only('firm.manage'))).toBe('/settings/firm')
    expect(railHref(RAIL_ITEMS[0]!, () => true)).toBe('/dashboard')
    expect(railHref(RAIL_ITEMS.find((i) => i.id === 'pipeline')!, () => true)).toBe('/pipeline')
  })
  it('lights a place from the address alone, and none inside a client', () => {
    expect(railActive('/dashboard')).toBe('dashboard')
    expect(railActive('/clients')).toBe('clients')
    expect(railActive('/pipeline')).toBe('pipeline')
    expect(railActive('/settings/team')).toBe('settings')
    expect(railActive('/clients/c1')).toBeUndefined()
    expect(railActive('/clients/c1/daybook')).toBeUndefined()
    expect(railActive('/bookkeeping')).toBeUndefined()
    expect(railActive('/soon/taxation')).toBeUndefined()
  })
})
