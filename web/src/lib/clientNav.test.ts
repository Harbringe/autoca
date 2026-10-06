import { CLIENT_NAV, clientScreenOf, clientScreenPath } from './clientNav'

describe('the selected client sidebar', () => {
  it('builds the address of each screen, the overview being the bare client', () => {
    expect(clientScreenPath('abc', '')).toBe('/clients/abc')
    expect(clientScreenPath('abc', 'daybook')).toBe('/clients/abc/daybook')
  })
  it('says which screen of a client the address is on', () => {
    expect(clientScreenOf('/clients/abc')).toBe('')
    expect(clientScreenOf('/clients/abc/tds')).toBe('tds')
    expect(clientScreenOf('/clients/abc/tds?fy=2025')).toBe('tds')
    expect(clientScreenOf('/dashboard')).toBeUndefined()
    expect(clientScreenOf('/clients')).toBeUndefined()
  })
  it('lists each screen once', () => {
    const screens = CLIENT_NAV.flatMap((g) => g.screens.map((s) => s.screen))
    expect(new Set(screens).size).toBe(screens.length)
  })
})
