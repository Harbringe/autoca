import { describe, expect, it } from 'vitest'
import type { JournalEntry, JournalLine } from '@/api/types'
import { particulars } from './PostedEntries'

function line(direction: 'DR' | 'CR', ledger_name: string): JournalLine {
  return { id: `${direction}-${ledger_name}`, ledger_account: ledger_name, ledger_name, direction, amount_paise: 100 } as JournalLine
}

function entry(lines: JournalLine[]): JournalEntry {
  return { id: 'e1', lines } as JournalEntry
}

describe('particulars', () => {
  it('names the ledger on each side of a simple entry', () => {
    expect(particulars(entry([line('DR', 'Bank Charges'), line('CR', 'Axis Bank A/c 7214')]))).toEqual({
      debit: 'Bank Charges',
      credit: 'Axis Bank A/c 7214',
    })
  })

  it('joins several ledgers on one side and lists each only once', () => {
    expect(particulars(entry([line('DR', 'Rent'), line('DR', 'GST Paid'), line('DR', 'Rent'), line('CR', 'Axis Bank A/c 7214')]))).toEqual({
      debit: 'Rent, GST Paid',
      credit: 'Axis Bank A/c 7214',
    })
  })

  it('is empty on a side with no lines', () => {
    expect(particulars(entry([line('DR', 'Rent')]))).toEqual({ debit: 'Rent', credit: '' })
  })
})
