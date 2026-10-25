// A payee the narration names (a person nobody has made a party of): the row can go to an account in their own name, a customer's under
// Sundry Debtors for a receipt, a supplier's under Sundry Creditors for a payment, instead of a general head like Sales.

import { raw } from '@/api/client'
import { V1 } from '@/api/queries/clients'
import type { Classification, LedgerAccount, Party } from '@/api/types'
import { titleCase } from '@/lib/format'

/** The payee's name as a person would write it, when this row should be offered their own account; otherwise null. */
export function namedPayee(row: Classification, canManageParties: boolean): string | null {
  const name = titleCase(row.counterparty ?? '')
  if (!canManageParties || !name || row.is_self_transfer || row.party || row.party_candidates?.length > 0) return null
  // Something is already sure of the row (a rule, a person, a confident assistant): leave it be.
  if (row.method === 'REVIEWED' || row.method === 'RULE') return null
  if (row.ledger && row.confidence >= 0.75) return null
  return name
}

export interface NamedGroup {
  key: string
  name: string
  debit: boolean
  rows: Classification[]
}

/** The rows to give their own accounts, one group for each payee and direction (a payee both paid and received is two accounts' worth of sides, one party). */
export function namedGroups(rows: Classification[], canManageParties: boolean): NamedGroup[] {
  const groups = new Map<string, NamedGroup>()
  for (const row of rows) {
    if (row.is_posted) continue
    const name = namedPayee(row, canManageParties)
    if (!name) continue
    const debit = row.transaction.is_debit
    const key = `${name.toLowerCase()}|${debit ? 'out' : 'in'}`
    const group = groups.get(key) ?? { key, name, debit, rows: [] }
    group.rows.push(row)
    groups.set(key, group)
  }
  return [...groups.values()]
}

/** Make the payee a party (or use the one with that name) and open their own account. The server leaves an account that already exists alone. */
export async function openOwnAccount(clientId: string, name: string, debit: boolean, known: Party[] | undefined): Promise<{ party: Party; account: LedgerAccount }> {
  const same = known?.find((p) => p.canonical_name.trim().toLowerCase() === name.trim().toLowerCase())
  const party = same ?? (await raw.post<Party>(`${V1}/clients/${clientId}/parties/`, { canonical_name: name, role: debit ? 'VENDOR' : 'CUSTOMER' }))
  const account = await raw.post<LedgerAccount>(`${V1}/clients/${clientId}/parties/${party.id}/account/`)
  return { party, account }
}
