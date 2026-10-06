import { describe, expect, it } from 'vitest'
import { invertLayout, layoutFrom } from './LayoutPicker'

describe('layoutFrom', () => {
  it('turns the chosen roles into a layout', () => {
    const { layout } = layoutFrom({ 0: 'date', 1: 'narration', 2: 'debit', 3: 'credit', 4: 'balance', 5: '' })
    expect(layout).toEqual({ date: 0, narration: 1, debit: 2, credit: 3, balance: 4 })
  })
  it('accepts one amount column in place of debit and credit', () => {
    expect(layoutFrom({ 0: 'date', 1: 'amount', 2: 'balance' }).layout).toEqual({ date: 0, amount: 1, balance: 2 })
  })
  it('says what is missing, in a sentence', () => {
    expect(layoutFrom({ 1: 'balance', 2: 'debit', 3: 'credit' }).problem).toBe('Mark the date column.')
    expect(layoutFrom({ 0: 'date', 2: 'debit', 3: 'credit' }).problem).toBe('Mark the balance column.')
    expect(layoutFrom({ 0: 'date', 1: 'balance', 2: 'debit' }).problem).toMatch(/debit and credit columns/)
  })
  it('refuses one role on two columns', () => {
    expect(layoutFrom({ 0: 'date', 1: 'date', 2: 'balance' }).problem).toMatch(/Two columns are marked as date/)
  })
})

describe('invertLayout', () => {
  it('maps the reader’s proposal back onto columns', () => {
    expect(invertLayout({ date: 0, balance: 4 })).toEqual({ 0: 'date', 4: 'balance' })
  })
})
