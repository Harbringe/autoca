import { beforeEach, describe, expect, it, vi } from 'vitest'

async function fresh() {
  vi.resetModules()
  return import('./pageSizes')
}

describe('rows per page', () => {
  beforeEach(() => localStorage.clear())

  it('gives each list its own size until one is chosen, with a ledger at 10', async () => {
    const p = await fresh()
    expect(p.pageSizeOf('ledger')).toBe(10)
    expect(p.pageSizeOf('review')).toBe(50)
    expect(p.pageSizeOf('statements')).toBe(100)
  })

  it('applies one size to every list, and a list on its own beats it', async () => {
    const p = await fresh()
    p.setAllPageSize(25)
    expect(p.pageSizeOf('review')).toBe(25)
    expect(p.pageSizeOf('ledger')).toBe(25)
    p.setSectionPageSize('ledger', 100)
    expect(p.pageSizeOf('ledger')).toBe(100)
    expect(p.pageSizeOf('daybook')).toBe(25)
    p.setSectionPageSize('ledger', null)
    expect(p.pageSizeOf('ledger')).toBe(25)
  })

  it('choosing all lists again clears the single-list choices, so all means all', async () => {
    const p = await fresh()
    p.setSectionPageSize('review', 10)
    p.setAllPageSize(50)
    expect(p.pageSizeOf('review')).toBe(50)
    p.setAllPageSize(null)
    expect(p.pageSizeOf('review')).toBe(50)
    expect(p.pageSizeOf('alerts')).toBe(10)
  })

  it('remembers the choice, and ignores a stored size that is not on offer', async () => {
    let p = await fresh()
    p.setSectionPageSize('daybook', 25)
    p = await fresh()
    expect(p.pageSizeOf('daybook')).toBe(25)
    localStorage.setItem('autoca.pageSizes', JSON.stringify({ all: 7, by: { review: 999 } }))
    p = await fresh()
    expect(p.pageSizeOf('review')).toBe(50)
  })
})
