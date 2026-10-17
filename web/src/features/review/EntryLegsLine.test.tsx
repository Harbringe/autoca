import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { EntryLeg } from '@/api/types'
import { bankSideOf, EntryLegsLine } from './EntryLegsLine'

const leg = (side: 'Dr' | 'Cr', ledger: string | null, amount: string, is_bank = false): EntryLeg => ({ side, ledger, is_bank, amount_display: amount })

describe('Which column the amount goes in', () => {
  it('is Debit when the bank account is debited, and Credit when it is credited', () => {
    expect(bankSideOf({ entry_legs: [leg('Cr', 'Sales', '₹1.00'), leg('Dr', 'Bank', '₹1.00', true)], transaction: { is_debit: false } })).toBe('Dr')
    expect(bankSideOf({ entry_legs: [leg('Dr', 'Rent', '₹1.00'), leg('Cr', 'Bank', '₹1.00', true)], transaction: { is_debit: true } })).toBe('Cr')
  })

  it('goes by the bank leg, so a loan account whose rows run the other way is right too', () => {
    expect(bankSideOf({ entry_legs: [leg('Cr', 'Cash', '₹1.00'), leg('Dr', 'Loan A/c', '₹1.00', true)], transaction: { is_debit: true } })).toBe('Dr')
  })

  it('falls back to the direction of the money when the server sent no legs', () => {
    expect(bankSideOf({ transaction: { is_debit: true } })).toBe('Cr')
    expect(bankSideOf({ transaction: { is_debit: false } })).toBe('Dr')
  })
})

describe('A split entry, as per details', () => {
  it('lists every other ledger under the row', () => {
    render(<EntryLegsLine legs={[leg('Dr', 'SRI SAPTHAGIRI INDUSTRIES', '₹2,40,000.00'), leg('Dr', 'Bank Charges', '₹23.60'), leg('Cr', 'SBI CC A/c', '₹2,40,023.60', true)]} />)
    const group = screen.getByRole('group', { name: /as per details/ })
    expect(group).toHaveTextContent('(as per details)')
    expect(group).toHaveTextContent('DrBank Charges₹23.60')
    expect(group).not.toHaveTextContent('SBI CC A/c')
  })

  it('shows nothing for an ordinary two-sided entry: its other ledger is the row itself', () => {
    const { container } = render(<EntryLegsLine legs={[leg('Dr', 'Interest Paid', '₹11,415.00'), leg('Cr', 'Generic Bank A/c 5259', '₹11,415.00', true)]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows nothing when the server sent no legs', () => {
    const { container } = render(<EntryLegsLine legs={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })
})
