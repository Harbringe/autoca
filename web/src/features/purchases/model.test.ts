import { describe, expect, it } from 'vitest'
import type { Bill, InvoiceReading } from '@/api/types'
import { buildItems, suggestLedger } from './model'

const bill = (over: Partial<Bill>): Bill =>
  ({ id: 'b1', kind: 'PURCHASE', party: 'p1', party_name: 'Ravi Traders', reference: 'INV-1', bill_date: '2025-10-01', total_paise: 118000, open_paise: 118000, document: null, has_document: false, created_at: '2025-10-01T10:00:00Z', ...over }) as unknown as Bill

const reading = (over: Partial<InvoiceReading>): InvoiceReading =>
  ({ id: 'r1', kind: 'PURCHASE', status: 'OPEN', document: 'd1', filename: 'ravi.pdf', proved: true, unreadable_reason: '', attention: '', auto_booked: false, checks: [], created_at: '2025-10-02T10:00:00Z', bill: null, read: null, ...over }) as unknown as InvoiceReading

describe('the Purchases & Sales list', () => {
  it('shows a booked file as its bill, a waiting file from what was read, and a bill with no file as itself', () => {
    const items = buildItems(
      [
        reading({ id: 'r1', status: 'BOOKED', bill: 'b1', auto_booked: true }),
        reading({ id: 'r2', document: 'd2', created_at: '2025-10-03T10:00:00Z', read: { supplier_name: 'Jubilant', supplier_address: 'Pune', invoice_no: 'J-9', invoice_date: '2025-09-27', total_paise: 108300, unsure: ['invoice_date'] } as never, proved: false, checks: [{ name: 'arithmetic', ok: false, detail: 'Taxable value plus tax does not equal the total.' }] }),
      ],
      [bill({ id: 'b1' }), bill({ id: 'b2', party_name: 'Shah', reference: 'S-1', bill_date: '2025-09-01', has_document: false })],
    )

    expect(items.map((i) => [i.party, i.status, i.as])).toEqual([
      ['Ravi Traders', 'Booked', 'reading'],
      ['Jubilant', 'Needs you', 'reading'],
      ['Shah', 'Booked', 'bill'],
    ])
    expect(items[0]!.alerts[0]).toMatch(/Booked automatically/)
    expect(items[1]!.detail).toBe('Pune')
    expect(items[1]!.alerts).toEqual(['Taxable value plus tax does not equal the total.', 'The reader was not sure of: invoice_date.'])
    expect(items[2]!.alerts).toEqual(['No invoice file is attached to this bill.'])
  })

  it('does not list a bill twice when its file is also in the list, and marks a settled one', () => {
    const items = buildItems([reading({ status: 'BOOKED', bill: 'b1' })], [bill({ id: 'b1', open_paise: 0 })])
    expect(items).toHaveLength(1)
    expect(items[0]!.status).toBe('Settled')
  })

  it('marks a file set aside', () => {
    expect(buildItems([reading({ status: 'DISCARDED' })], [])[0]).toMatchObject({ setAside: true, status: 'Set aside', alerts: [] })
  })
})

describe('suggesting a ledger from what the receipt says it was for', () => {
  const ledgers = [
    { id: 'l1', name: 'Purchases' },
    { id: 'l2', name: 'Food & Beverages Expenses' },
    { id: 'l3', name: 'Office Rent' },
    { id: 'l4', name: 'Rent Received' },
  ]
  it('picks the ledger sharing the most words', () => {
    expect(suggestLedger('Food and beverages', ledgers)).toBe('l2')
    expect(suggestLedger('Office rent', ledgers)).toBe('l3')
  })
  it('prefers the shorter name on a tie and says nothing when nothing is shared', () => {
    expect(suggestLedger('Rent', ledgers)).toBe('l3')
    expect(suggestLedger('Laptop', ledgers)).toBeUndefined()
    expect(suggestLedger('', ledgers)).toBeUndefined()
  })
})
