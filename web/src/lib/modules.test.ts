import { describe, expect, it } from 'vitest'
import { clientIdOf, moduleOf, switchClientPath } from './modules'

describe('moduleOf', () => {
  it('puts each client screen under its module', () => {
    expect(moduleOf('/clients')).toBe('clients')
    expect(moduleOf('/clients/abc')).toBe('clients')
    expect(moduleOf('/clients/abc/team')).toBe('clients')
    expect(moduleOf('/clients/abc/statements')).toBe('bank')
    expect(moduleOf('/clients/abc/review')).toBe('bank')
    expect(moduleOf('/clients/abc/masters')).toBe('bookkeeping')
    expect(moduleOf('/clients/abc/books')).toBe('bookkeeping')
    expect(moduleOf('/clients/abc/reports')).toBe('reports')
  })
  it('knows the firm-level pages and the coming-soon pages', () => {
    expect(moduleOf('/pipeline')).toBe('pipeline')
    expect(moduleOf('/staff')).toBe('staff')
    expect(moduleOf('/settings/team')).toBe('settings')
    expect(moduleOf('/soon/taxation')).toBe('taxation')
    expect(moduleOf('/soon/nothing')).toBeUndefined()
    expect(moduleOf('/')).toBeUndefined()
  })
})

describe('clientIdOf', () => {
  it('reads the client from the address', () => {
    expect(clientIdOf('/clients/abc/daybook')).toBe('abc')
    expect(clientIdOf('/clients')).toBeUndefined()
    expect(clientIdOf('/staff')).toBeUndefined()
  })
})

describe('switchClientPath', () => {
  it('keeps the module and the tab when the client changes', () => {
    expect(switchClientPath('/clients/A/daybook', 'B')).toBe('/clients/B/daybook')
    expect(switchClientPath('/clients/A/review', 'B')).toBe('/clients/B/review')
    expect(switchClientPath('/clients/A', 'B')).toBe('/clients/B')
  })
  it('opens the module for the client from its firm landing', () => {
    expect(switchClientPath('/bookkeeping', 'B')).toBe('/clients/B/daybook')
    expect(switchClientPath('/bank', 'B')).toBe('/clients/B/statements')
    expect(switchClientPath('/reports', 'B')).toBe('/clients/B/reports')
  })
  it('falls back to the profile from pages that are not a client module', () => {
    expect(switchClientPath('/clients', 'B')).toBe('/clients/B')
    expect(switchClientPath('/staff', 'B')).toBe('/clients/B')
    expect(switchClientPath('/gst', 'B')).toBe('/clients/B')
  })
  it('goes to the module landing for All clients', () => {
    expect(switchClientPath('/clients/A/daybook', null)).toBe('/bookkeeping')
    expect(switchClientPath('/clients/A/statements', null)).toBe('/bank')
    expect(switchClientPath('/clients/A/reports', null)).toBe('/reports')
    expect(switchClientPath('/clients/A', null)).toBe('/clients')
    expect(switchClientPath('/staff', null)).toBe('/clients')
  })
})
