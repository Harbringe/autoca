import { describe, expect, it } from 'vitest'
import { JUMP_KEYS, moduleHref } from './jump'

describe('moduleHref', () => {
  it('opens a module at its firm landing under All clients', () => {
    expect(moduleHref('bookkeeping')).toBe('/bookkeeping')
    expect(moduleHref('bank')).toBe('/bank')
    expect(moduleHref('reports')).toBe('/reports')
    expect(moduleHref('gst')).toBe('/gst')
    expect(moduleHref('dashboard')).toBe('/dashboard')
    expect(moduleHref('clients')).toBe('/clients')
  })
  it('opens the module on the client’s own screen when a client is open', () => {
    expect(moduleHref('bookkeeping', 'A')).toBe('/clients/A/bookkeeping')
    expect(moduleHref('bank', 'A')).toBe('/clients/A/statements')
    expect(moduleHref('reports', 'A')).toBe('/clients/A/reports')
    expect(moduleHref('gst', 'A')).toBe('/clients/A/gst')
  })
  it('keeps the client list and the dashboard firm-wide', () => {
    expect(moduleHref('clients', 'A')).toBe('/clients')
    expect(moduleHref('dashboard', 'A')).toBe('/dashboard')
  })
})

describe('JUMP_KEYS', () => {
  it('has one key per module, none repeated, and no clash with the other g keys', () => {
    const keys = JUMP_KEYS.map((j) => j.key)
    expect(new Set(keys).size).toBe(keys.length)
    expect(keys.sort().join('')).toBe('bcdgrs')
    // g w, g t, g f (staff, team, firm) and the client tabs g o, g v, g l, g m, g k, g e stay free of these.
    for (const other of ['w', 't', 'f', 'o', 'v', 'l', 'm', 'k', 'e']) expect(keys).not.toContain(other)
  })
})
