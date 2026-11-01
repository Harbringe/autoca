import { describe, expect, it } from 'vitest'
import { amountInWords } from './amountInWords'

describe('amountInWords', () => {
  it('writes whole rupees in the Indian system', () => {
    expect(amountInWords(0)).toBe('Rupees Zero Only')
    expect(amountInWords(100)).toBe('Rupees One Only')
    expect(amountInWords(1_00_000_00)).toBe('Rupees One Lakh Only')
    expect(amountInWords(12_34_567_00)).toBe('Rupees Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven Only')
    expect(amountInWords(2_50_00_000_00)).toBe('Rupees Two Crore Fifty Lakh Only')
  })

  it('adds the paise', () => {
    expect(amountInWords(118_050)).toBe('Rupees One Thousand One Hundred Eighty and Fifty Paise Only')
    expect(amountInWords(5)).toBe('Rupees Zero and Five Paise Only')
  })

  it('handles the teens and round tens', () => {
    expect(amountInWords(1_900)).toBe('Rupees Nineteen Only')
    expect(amountInWords(40_000)).toBe('Rupees Four Hundred Only')
    expect(amountInWords(11_000_00)).toBe('Rupees Eleven Thousand Only')
  })

  it('writes a negative amount with a minus', () => {
    expect(amountInWords(-1_000)).toBe('Minus Rupees Ten Only')
  })

  it('refuses a figure that is not whole paise', () => {
    expect(() => amountInWords(10.5)).toThrow()
  })
})
