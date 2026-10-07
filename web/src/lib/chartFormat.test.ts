import { describe, expect, it } from 'vitest'
import { axisMoney, monthLong, monthShort } from './chartFormat'

describe('axisMoney', () => {
  it('shows small figures in full rupees with Indian grouping', () => {
    expect(axisMoney(0)).toBe('₹0')
    expect(axisMoney(5_000_000)).toBe('₹50,000')
  })
  it('switches to lakh and crore from a lakh up', () => {
    expect(axisMoney(15_000_000)).toBe('₹1.5 L')
    expect(axisMoney(2_000_000_000)).toBe('₹2 Cr')
  })
})

describe('month names', () => {
  it('names a month from YYYY-MM', () => {
    expect(monthShort('2026-04')).toBe('Apr')
    expect(monthLong('2027-03')).toBe('March 2027')
  })
})
