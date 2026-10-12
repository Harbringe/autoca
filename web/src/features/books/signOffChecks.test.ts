import { describe, expect, it } from 'vitest'
import { checkFigure, signOffHeadline } from './signOffChecks'

describe('checkFigure', () => {
  it('reads the count from the rows and assistant checks', () => {
    expect(checkFigure({ name: 'rows_posted', ok: false, detail: '11 transactions still need a decision.' })).toBe('11 to decide')
    expect(checkFigure({ name: 'assistant_entries_checked', ok: false, detail: '4 entries not yet marked as checked.' })).toBe('4 to check')
  })
  it('reads the difference from a bank check', () => {
    const detail = 'Generic Bank A/c 0365 does not reconcile at 06-01-2026. The books say ₹1,24,66,449.31; the bank says ₹13,83,437.31; the difference is ₹1,10,83,012.00. 11 transaction(s) up to that date have not been posted.'
    expect(checkFigure({ name: 'bank_abc', ok: false, detail })).toBe('₹1,10,83,012.00')
  })
  it('shows nothing for a passing check or wording it does not know', () => {
    expect(checkFigure({ name: 'rows_posted', ok: true, detail: '' })).toBeNull()
    expect(checkFigure({ name: 'suspense_clear', ok: false, detail: 'The Suspense account has a balance.' })).toBeNull()
    expect(checkFigure({ name: 'bank_x', ok: false, detail: 'Something else.' })).toBeNull()
  })
})

describe('signOffHeadline', () => {
  it('counts what is left to clear for a draft', () => {
    expect(signOffHeadline({ state: 'draft', toClear: 3, known: true })).toBe('Three things to clear before you can send the books for review.')
    expect(signOffHeadline({ state: 'draft', toClear: 1, known: true })).toBe('One thing to clear before you can send the books for review.')
    expect(signOffHeadline({ state: 'draft', toClear: 0, known: true })).toBe('Every check passes. You can send the books for review.')
  })
  it('says where the books are in the other states', () => {
    expect(signOffHeadline({ state: 'awaiting_senior', toClear: 0, known: true, leadName: 'owner_rudra' })).toBe('The books are with owner_rudra for approval.')
    expect(signOffHeadline({ state: 'approved', toClear: 0, known: true, nextSealDate: '30-06-2025' })).toBe('The books are approved. They will be sealed on 30-06-2025.')
    expect(signOffHeadline({ state: 'returned', toClear: 2, known: true })).toMatch(/returned with a note/)
  })
  it('waits for the report before counting', () => {
    expect(signOffHeadline({ state: 'draft', toClear: 0, known: false })).toBe('Checking what is open…')
  })
})
