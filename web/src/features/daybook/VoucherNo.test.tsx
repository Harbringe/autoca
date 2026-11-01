import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { entryMatches } from './entryMatches'
import { VoucherNo } from './VoucherNo'

describe('VoucherNo', () => {
  it("shows Tally's number beside ours on an imported voucher", () => {
    render(<VoucherNo entryNo={1} tallyNumber="138" />)
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('Tally 138')).toBeInTheDocument()
  })

  it('shows only our number when the voucher did not come from Tally', () => {
    render(<VoucherNo entryNo={7} tallyNumber="" />)
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.queryByText(/Tally/)).not.toBeInTheDocument()
  })

  it('shows a number in the client format as written', () => {
    render(<VoucherNo entryNo="S/26-27/0001" tallyNumber="" />)
    expect(screen.getByText('S/26-27/0001')).toBeInTheDocument()
  })
})

describe('entryMatches', () => {
  const entry = { narration: 'Rent for April', tally_number: '138', lines: [{ ledger_name: 'Rent', party_name: 'Acme Traders' }] }

  it('finds an entry by its Tally number', () => {
    expect(entryMatches(entry, '138')).toBe(true)
    expect(entryMatches(entry, '139')).toBe(false)
  })

  it('still finds by narration, ledger or party, ignoring case', () => {
    expect(entryMatches(entry, 'rent for')).toBe(true)
    expect(entryMatches(entry, 'acme')).toBe(true)
    expect(entryMatches(entry, '')).toBe(true)
  })

  it('copes with an entry that has no Tally number', () => {
    expect(entryMatches({ ...entry, tally_number: undefined }, '138')).toBe(false)
  })
})
