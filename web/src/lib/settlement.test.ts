import { describe, expect, it } from 'vitest'
import { basisNote, decide, draftFrom, type BillRef } from './settlement'

const BILLS: BillRef[] = [
  { id: 'a', reference: 'INV-1', open_paise: 10_000_00 },
  { id: 'b', reference: 'INV-2', open_paise: 5_000_00 },
]
const PAYMENT = 12_000_00

describe('draftFrom', () => {
  it('turns the server’s suggestion into amounts a person can edit', () => {
    const draft = draftFrom({ allocations: [{ bill: 'a', amount_paise: 10_000_00 }, { bill: 'b', amount_paise: 2_000_00 }] })
    expect(draft.amounts).toEqual({ a: '10000.00', b: '2000.00' })
    expect(draft.remainder).toBe('ON_ACCOUNT')
  })
})

describe('decide', () => {
  it('adds up what is typed against the bills and says what is left to hold', () => {
    const d = decide(PAYMENT, BILLS, { amounts: { a: '10,000', b: '1,000' }, remainder: 'ADVANCE' })
    expect(d.allocations).toEqual([{ bill: 'a', amount_paise: 10_000_00 }, { bill: 'b', amount_paise: 1_000_00 }])
    expect(d.allocated).toBe(11_000_00)
    expect(d.left).toBe(1_000_00)
    expect(d.remainder).toBe('ADVANCE')
    expect(d.problem).toBeNull()
  })

  it('a payment that exactly clears the bills leaves nothing to hold', () => {
    const d = decide(PAYMENT, BILLS, { amounts: { a: '10000', b: '2000' }, remainder: 'ON_ACCOUNT' })
    expect(d.left).toBe(0)
    expect(d.remainder).toBeNull()
  })

  it('no bill at all is allowed: the whole payment is held', () => {
    const d = decide(PAYMENT, BILLS, { amounts: {}, remainder: 'ADVANCE' })
    expect(d.allocations).toEqual([])
    expect(d.left).toBe(PAYMENT)
    expect(d.remainder).toBe('ADVANCE')
    expect(d.problem).toBeNull()
  })

  it('refuses bills that add up to more than moved, saying so', () => {
    const d = decide(PAYMENT, BILLS, { amounts: { a: '10000', b: '5000' }, remainder: 'ON_ACCOUNT' })
    expect(d.problem).toContain('more than the')
    expect(d.left).toBe(0)
  })

  it('flags a bill given more than is open on it', () => {
    const d = decide(PAYMENT, BILLS, { amounts: { b: '6000' }, remainder: 'ON_ACCOUNT' })
    expect(d.fieldErrors.b).toContain('Only')
    expect(d.problem).toBe('Fix the amounts marked below.')
  })

  it.each(['abc', '12.345', '-5', '0'])('flags “%s” as not an amount', (text) => {
    const d = decide(PAYMENT, BILLS, { amounts: { a: text }, remainder: 'ON_ACCOUNT' })
    expect(d.fieldErrors.a).toBeDefined()
  })

  it('ignores a blank field and a bill that is not in the list', () => {
    const d = decide(PAYMENT, BILLS, { amounts: { a: '  ', zzz: '5' }, remainder: 'ON_ACCOUNT' })
    expect(d.allocations).toEqual([])
    expect(d.fieldErrors).toEqual({})
  })
})

describe('basisNote', () => {
  it('says how sure the suggestion is', () => {
    expect(basisNote('exact_one', ['INV-1'])).toBe('This is exactly INV-1.')
    expect(basisNote('exact_set', ['A', 'B'])).toBe('These 2 bills add up to exactly this payment.')
    expect(basisNote('oldest_first', [])).toContain('oldest bills first')
    expect(basisNote('none', [])).toContain('nothing open')
  })
})
