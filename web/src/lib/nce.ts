// The lines of the ICAI non-corporate Balance Sheet and Statement of Profit and Loss a ledger can be placed on by hand.
// Mirrors ledger/nce.py; the server refuses any code that is not one of these.

export const NCE_LINES: { group: string; lines: [code: string, label: string][] }[] = [
  {
    group: 'Equity and liabilities',
    lines: [
      ['EQ.CAP', "Owners' Capital Account"],
      ['EQ.RES', 'Reserves and surplus'],
      ['NCL.BORR', 'Long-term borrowings'],
      ['NCL.DTL', 'Deferred tax liabilities (Net)'],
      ['NCL.OTH', 'Other long-term liabilities'],
      ['NCL.PROV', 'Long-term provisions'],
      ['CL.BORR', 'Short-term borrowings'],
      ['CL.PAY', 'Trade payables'],
      ['CL.OTH', 'Other current liabilities'],
      ['CL.PROV', 'Short-term provisions'],
    ],
  },
  {
    group: 'Assets',
    lines: [
      ['NCA.PPE', 'Property, Plant and Equipment'],
      ['NCA.INTANG', 'Intangible assets'],
      ['NCA.CWIP', 'Capital work in progress'],
      ['NCA.IAUD', 'Intangible asset under development'],
      ['NCA.INV', 'Non-current investments'],
      ['NCA.DTA', 'Deferred tax assets (Net)'],
      ['NCA.LOANS', 'Long term loans and advances'],
      ['NCA.OTH', 'Other non-current assets'],
      ['CA.INV', 'Current investments'],
      ['CA.STOCK', 'Inventories'],
      ['CA.REC', 'Trade receivables'],
      ['CA.CASH', 'Cash and bank balances'],
      ['CA.LOANS', 'Short term loans and advances'],
      ['CA.OTH', 'Other current assets'],
    ],
  },
  {
    group: 'Statement of Profit and Loss',
    lines: [
      ['PL.REV', 'Revenue from operations'],
      ['PL.OTH', 'Other income'],
      ['PL.COGS', 'Cost of goods sold'],
      ['PL.EMP', 'Employee benefits expense'],
      ['PL.FIN', 'Finance costs'],
      ['PL.DEP', 'Depreciation and amortization expense'],
      ['PL.EXP', 'Other expenses'],
      ['PL.PREM', "Partners' remuneration"],
      ['PL.TAXC', 'Current tax'],
      ['PL.TAXD', 'Deferred tax charge/(benefit)'],
    ],
  },
]
