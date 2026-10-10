import { describe, expect, it } from 'vitest'
import type { Party } from '@/api/types'
import { proposals } from './TidyNames'

const party = (id: string, canonical_name: string) => ({ id, canonical_name }) as Party

describe('names to tidy', () => {
  it('offers only the names that would change', () => {
    const found = proposals([party('1', 'RAVI TRADERS'), party('2', 'Ravi Traders')])
    expect(found.map((f) => f.party.id)).toEqual(['1'])
    expect(found[0]!.to).toBe('Ravi Traders')
  })
})
