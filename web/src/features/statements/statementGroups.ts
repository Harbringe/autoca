// A client's statements laid out under the bank account they belong to, so each account shows its own
// opening balance next to its own statements. Pure, so it is tested.

export interface GroupedAccount<A, S> {
  account: A
  statements: S[]
}

/**
 * Accounts in the order given, each with its statements. A statement whose account is not in the list is
 * returned in `orphans` and never dropped, so a figure on file is never hidden by a missing account row.
 */
export function groupByAccount<A extends { id: string }, S extends { bank_account: string }>(
  accounts: A[],
  statements: S[],
): { groups: GroupedAccount<A, S>[]; orphans: S[] } {
  const known = new Set(accounts.map((a) => a.id))
  return {
    groups: accounts.map((account) => ({ account, statements: statements.filter((s) => s.bank_account === account.id) })),
    orphans: statements.filter((s) => !known.has(s.bank_account)),
  }
}

/** The line above the rows bar: how many rows were read and how many still need a person. */
export function rowsHeadline(rowsOnFile: number, waiting: number): string {
  if (rowsOnFile === 0) return 'No rows read yet'
  const read = `${rowsOnFile} ${rowsOnFile === 1 ? 'row' : 'rows'} read`
  return waiting > 0 ? `${read}, ${waiting} still ${waiting === 1 ? 'needs' : 'need'} you` : `${read}, all posted`
}
