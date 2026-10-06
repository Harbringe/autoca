// Purchase and sales vouchers, as the bills they book.
//
// Posting or removing a voucher changes more than the bills list: the Day Book gains or loses an entry, the party gains
// its account, and the open items and reports move. So a successful change marks everything about the client stale (the
// same prefix every other change to the books uses) instead of patching one list, which is how two screens come to
// disagree about the same voucher.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { Bill, CloseReport, FoundParties, InvoiceReading, BillCreateRequest, BillDetail, OpenItems, OpeningStanding, Outstanding, PartyStatement, SettlementContext } from '@/api/types'
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
    mutationFn: ({ file, kind }: { file: File; kind: 'PURCHASE' | 'SALES' }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('kind', kind)
      return raw.post<InvoiceReading>(`${V1}/clients/${clientId}/invoices/upload/`, form)
    },
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
