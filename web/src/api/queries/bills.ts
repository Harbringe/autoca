// Purchase and sales vouchers, as the bills they book.
//
// Posting or removing a voucher changes more than the bills list: the Day Book gains or loses an entry, the party gains
// its account, and the open items and reports move. So a successful change marks everything about the client stale (the
// same prefix every other change to the books uses) instead of patching one list, which is how two screens come to
// disagree about the same voucher.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { AssetSchedule, TdsSummary, Bill, CloseReport, FoundParties, InvoiceReading, BillCreateRequest, BillDetail, OpenItems, OpeningStanding, Outstanding, PartyStatement, SettlementContext } from '@/api/types'
import { allPages } from './books'
import { clientKeys, useInvalidateClient, V1 } from './clients'

export interface BillFilters {
  kind?: string
  party?: string
  status?: 'open' | 'settled'
  fy?: number
  q?: string
}

export const bills = (clientId: string, filters: BillFilters = {}) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'bills', filters),
    queryFn: () => allPages<Bill>(`${V1}/clients/${clientId}/bills/`, { ...filters }),
  })

export const bill = (clientId: string, billId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'bills', billId),
    queryFn: () => raw.get<BillDetail>(`${V1}/clients/${clientId}/bills/${billId}/`),
  })

/** The party's open bills for a payment on its account, and how the payment would clear them: only a suggestion. */
export const rowSettlement = (clientId: string, classificationId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'settlement', classificationId),
    queryFn: () => raw.get<SettlementContext>(`${V1}/classifications/${classificationId}/settlement/`),
  })

/** What the client owes its suppliers, or its customers owe it, bill by bill, aged, as at a date (ISO). */
export const outstanding = (clientId: string, side: 'payables' | 'receivables', asOf: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'outstanding', side, asOf),
    queryFn: () => raw.get<Outstanding>(`${V1}/clients/${clientId}/outstanding/`, { side, as_of: asOf }),
  })

/** One party's account, line by line with a running balance, between two ISO dates. */
export const partyStatement = (clientId: string, partyId: string, from: string, to: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'parties', partyId, 'statement', from, to),
    queryFn: () => raw.get<PartyStatement>(`${V1}/clients/${clientId}/parties/${partyId}/statement/`, { date_from: from, date_to: to }),
  })

export function usePostBill(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: BillCreateRequest) => raw.post<BillDetail>(`${V1}/clients/${clientId}/bills/`, body),
    onSuccess: invalidate,
  })
}

/** Replace a booked bill with its corrected version in one step (the old one is kept in the change log). */
export function useReviseBill(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: BillCreateRequest }) =>
      raw.post<BillDetail>(`${V1}/clients/${clientId}/bills/${id}/revise/`, body),
    onSuccess: invalidate,
  })
}

export function useRemoveBill(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      raw.post<void>(`${V1}/clients/${clientId}/bills/${id}/remove/`, { note }),
    onSuccess: invalidate,
  })
}

/** Everything that does not yet tie out for the client, oldest first; `kind` narrows the list but not the counts. */
export const openItems = (clientId: string, kind = '') =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'open-items', kind),
    queryFn: () => raw.get<OpenItems>(`${V1}/clients/${clientId}/open-items/`, kind ? { kind } : {}),
  })

/** A posted payment's open bills, for settling it after the fact. */
export const entrySettlement = (clientId: string, entryId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'entry-settlement', entryId),
    queryFn: () => raw.get<SettlementContext>(`${V1}/journal-entries/${entryId}/settlement/`),
  })

/** Say why a payment to a party with bills has no invoice against it (blank unsays it). */
export function useSetBillStatus(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ entry, status }: { entry: string; status: '' | 'NO_INVOICE_EXPECTED' | 'NEEDS_INVOICE' }) =>
      raw.post<{ status: string }>(`${V1}/journal-entries/${entry}/bill-status/`, { status }),
    onSuccess: invalidate,
  })
}

/** Settle the unallocated part of a posted payment, as a person decided. */
export function useSettleEntry(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ entry, allocations, remainder }: { entry: string; allocations: { bill: string; amount_paise: number }[]; remainder: string | null }) =>
      raw.post<{ settled_paise: number }>(`${V1}/journal-entries/${entry}/settle/`, { allocations, remainder }),
    onSuccess: invalidate,
  })
}

/** A party's imported opening balance, and how much of it is already broken into bills. */
export const partyOpening = (clientId: string, partyId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'parties', partyId, 'opening'),
    queryFn: () => raw.get<OpeningStanding>(`${V1}/clients/${clientId}/parties/${partyId}/opening/`),
  })

/** Break an opening balance into the invoices it is made of. */
export function useBreakDownOpening(clientId: string, partyId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (bills: { reference: string; bill_date: string; amount_paise: number }[]) =>
      raw.post<OpeningStanding>(`${V1}/clients/${clientId}/parties/${partyId}/opening-bills/`, { bills }),
    onSuccess: invalidate,
  })
}

/** Invoices uploaded as files, newest first, with what was read from each. */
export const invoiceReadings = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'invoices'),
    queryFn: () => allPages<InvoiceReading>(`${V1}/clients/${clientId}/invoices/`),
  })

export function useUploadInvoice(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    // No kind: the server tells a purchase from a sale by the client's own GSTIN and books it when certain.
    mutationFn: ({ file, kind }: { file: File; kind?: 'PURCHASE' | 'SALES' }) => {
      const form = new FormData()
      form.append('file', file)
      if (kind) form.append('kind', kind)
      return raw.post<InvoiceReading>(`${V1}/clients/${clientId}/invoices/upload/`, form)
    },
    onSuccess: invalidate,
  })
}

/** A person says what the system could not tell; it then tries to book the invoice as usual. */
export function useSayInvoiceKind(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ id, kind }: { id: string; kind: 'PURCHASE' | 'SALES' }) =>
      raw.post<InvoiceReading>(`${V1}/clients/${clientId}/invoices/${id}/kind/`, { kind }),
    onSuccess: invalidate,
  })
}

export function useDecideInvoice(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ id, action, bill }: { id: string; action: 'attach' | 'discard'; bill?: string }) =>
      raw.post<InvoiceReading>(`${V1}/clients/${clientId}/invoices/${id}/${action}/`, bill ? { bill } : {}),
    onSuccess: invalidate,
  })
}

/** Every control and open item between the books and sign-off, and the reasons given for the ones that may stand. */
export const closeReport = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'close'),
    queryFn: () => raw.get<CloseReport>(`${V1}/clients/${clientId}/books/close/`),
  })

export function useExplainItem(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ itemKey, note }: { itemKey: string; note: string }) =>
      raw.post<CloseReport>(`${V1}/clients/${clientId}/books/close/explain/`, { item_key: itemKey, note }),
    onSuccess: invalidate,
  })
}

export function useWithdrawExplanation(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (itemKey: string) => raw.post<CloseReport>(`${V1}/clients/${clientId}/books/close/withdraw/`, { item_key: itemKey }),
    onSuccess: invalidate,
  })
}

/** Counterparties in the statements that look like suppliers or customers, for a person to tick. */
export const partyCandidates = (clientId: string, oneOffs = false) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'parties', 'found', oneOffs),
    queryFn: () => raw.get<FoundParties>(`${V1}/clients/${clientId}/parties/found/`, oneOffs ? { one_offs: 'true' } : {}),
  })

export function useCreateFoundParties(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (parties: { name: string; role: string }[]) =>
      raw.post<{ created: number }>(`${V1}/clients/${clientId}/parties/found/`, { parties }),
    onSuccess: invalidate,
  })
}

/** A posted payment booked to some head: its party's open bills, if it were moved onto the party's account. */
export const entryMoveContext = (clientId: string, entryId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'entry-move', entryId),
    queryFn: () => raw.get<SettlementContext>(`${V1}/journal-entries/${entryId}/move-to-party/`),
  })

/** Move a posted payment onto its party's account and settle it, as a person decided. */
export function useMoveToParty(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ entry, allocations, remainder }: { entry: string; allocations: { bill: string; amount_paise: number }[]; remainder: string | null }) =>
      raw.post<{ settled_paise: number }>(`${V1}/journal-entries/${entry}/move-to-party/`, { allocations, remainder }),
    onSuccess: invalidate,
  })
}

/** The asset register's depreciation schedule for one financial year (starting year, 2025 for FY 2025-26). */
export const assetSchedule = (clientId: string, year: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'assets', year),
    queryFn: () => raw.get<AssetSchedule>(`${V1}/clients/${clientId}/assets/schedule/`, { fy: year }),
  })

export function useRegisterAsset(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => raw.post<unknown>(`${V1}/clients/${clientId}/assets/`, body),
    onSuccess: invalidate,
  })
}

export function useAssetAction(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ id, action, body }: { id: string; action: 'dispose' | 'remove'; body?: Record<string, unknown> }) =>
      raw.post<unknown>(`${V1}/clients/${clientId}/assets/${id}/${action}/`, body ?? {}),
    onSuccess: invalidate,
  })
}

/** Whether a year's depreciation is booked, and whether the register still agrees with what was booked. */
export const depreciationStatus = (clientId: string, year: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'depreciation', year),
    queryFn: () =>
      raw.get<{ year: number; planned_paise: number; planned_display: string; posted_paise: number | null; posted_display: string | null; entry: string | null; stale: boolean }>(
        `${V1}/clients/${clientId}/assets/depreciation/`,
        { fy: year },
      ),
  })

export function useBookDepreciation(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ year, remove }: { year: number; remove?: boolean }) =>
      raw.post<unknown>(`${V1}/clients/${clientId}/assets/depreciation/${remove ? 'remove/' : ''}`, { fy: year }),
    onSuccess: invalidate,
  })
}

/** TDS deducted, deposited and due, by section and month; and deposits that have no challan recorded. */
export const tdsSummary = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'tds'),
    queryFn: () => raw.get<TdsSummary>(`${V1}/clients/${clientId}/tds/summary/`),
  })

export function useRecordChallan(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: { entry: string; section: string; bsr_code: string; serial: string; paid_on: string }) =>
      raw.post<unknown>(`${V1}/clients/${clientId}/tds/`, body),
    onSuccess: invalidate,
  })
}

/** The people the client pays a salary to. */
export const employees = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'employees'),
    queryFn: () => allPages<{ id: string; name: string; is_active: boolean; ledger: string | null }>(`${V1}/clients/${clientId}/employees/`),
  })

/** Salary runs already booked, newest first. */
export const payrollRuns = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'payroll'),
    queryFn: () =>
      allPages<{ id: string; year: number; month: number; entry: string; gross_paise: number; gross_display: string; net_paise: number; net_display: string }>(
        `${V1}/clients/${clientId}/payroll/`,
      ),
  })

export function useAddEmployee(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (name: string) => raw.post<unknown>(`${V1}/clients/${clientId}/employees/`, { name }),
    onSuccess: invalidate,
  })
}

export interface SalaryLine {
  employee: string
  gross_paise: number
  pf_employee_paise: number
  pf_employer_paise: number
  esi_employee_paise: number
  esi_employer_paise: number
  tds_paise: number
  other_deduction_paise: number
}

export function useBookSalaries(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: { year: number; month: number; lines: SalaryLine[] }) => raw.post<unknown>(`${V1}/clients/${clientId}/payroll/`, body),
    onSuccess: invalidate,
  })
}

export function useRemoveSalaries(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (id: string) => raw.post<unknown>(`${V1}/clients/${clientId}/payroll/${id}/remove/`, {}),
    onSuccess: invalidate,
  })
}
