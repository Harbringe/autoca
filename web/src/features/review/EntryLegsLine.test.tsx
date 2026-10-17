import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { EntryLeg } from '@/api/types'
import { EntryLegsLine } from './EntryLegsLine'

const leg = (side: 'Dr' | 'Cr', ledger: string | null, amount: string, is_bank = false): EntryLeg => ({ side, ledger, is_bank, amount_display: amount })

describe('The Dr and Cr of a row, in the list', () => {
  it('shows both sides with their ledgers and amounts', () => {
    render(<EntryLegsLine legs={[leg('Dr', 'Interest Paid', '₹11,415.00'), leg('Cr', 'Generic Bank A/c 5259', '₹11,415.00', true)]} />)
    const group = screen.getByRole('group', { name: 'The entry this makes' })
    expect(group).toHaveTextContent('DrInterest Paid₹11,415.00')
    expect(group).toHaveTextContent('CrGeneric Bank A/c 5259₹11,415.00')
  })

  it('shows nothing while the other side is not chosen yet', () => {
    const { container } = render(<EntryLegsLine legs={[leg('Dr', null, '₹708.00'), leg('Cr', 'Generic Bank A/c 5259', '₹708.00', true)]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows nothing when the server sent no legs', () => {
    const { container } = render(<EntryLegsLine legs={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows every leg of a split entry', () => {
    render(<EntryLegsLine legs={[leg('Dr', 'SRI SAPTHAGIRI INDUSTRIES', '₹2,40,000.00'), leg('Dr', 'Bank Charges', '₹23.60'), leg('Cr', 'SBI CC A/c', '₹2,40,023.60', true)]} />)
    expect(screen.getByRole('group')).toHaveTextContent('Bank Charges₹23.60')
  })
})
