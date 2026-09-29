import { keepPreviousData, queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, data, raw } from '@/api/client'
import type { components } from '@/api/schema'
import type { BankAccount, BooksStatus, Client, Page, ReviewSummary, Statement } from '@/api/types'

export type ClientRequest = components['schemas']['ClientRequest']

// Every key for one client's data starts ['client', id], so a change to that client's books
// can mark all of it stale with one prefix. The firm-wide list of clients is ['clients', ...].
export const clientKeys = {
  all: ['clients'] as const,
  list: (search: string, page: number) => ['clients', 'list', search, page] as const,
  one: (id: string) => ['client', id] as const,
  part: (id: string, ...rest: unknown[]) => ['client', id, ...rest] as const,
}

export const V1 = '/api/v1'

export const clientsList = (search: string, page = 1) =>
  queryOptions({
    queryKey: clientKeys.list(search, page),
    // The schema calls `lead` an untyped object; api/types.ts says what it holds.
    queryFn: async () =>
      data(await api.GET('/api/v1/clients/', { params: { query: { search: search || undefined, page } } })) as unknown as Page<Client>,
    placeholderData: keepPreviousData,
  })

export const clientDetail = (id: string) =>
  queryOptions({
    queryKey: [...clientKeys.one(id), 'detail'],
    queryFn: async () => data(await api.GET('/api/v1/clients/{id}/', { params: { path: { id } } })) as unknown as Client,
  })

export const reviewSummary = (id: string) =>
  queryOptions({
    queryKey: clientKeys.part(id, 'summary'),
    queryFn: () => raw.get<ReviewSummary>(`${V1}/clients/${id}/review-queue/summary/`),
  })

export const booksStatus = (id: string) =>
  queryOptions({
    queryKey: clientKeys.part(id, 'books'),
    queryFn: () => raw.get<BooksStatus>(`${V1}/clients/${id}/books/`),
  })

export const bankAccounts = (id: string) =>
  queryOptions({
    queryKey: clientKeys.part(id, 'bank-accounts'),
    queryFn: () => raw.get<Page<BankAccount>>(`${V1}/clients/${id}/bank-accounts/`, { page_size: 100 }),
  })

export const statements = (id: string) =>
  queryOptions({
    queryKey: clientKeys.part(id, 'statements'),
    queryFn: () => raw.get<Page<Statement>>(`${V1}/clients/${id}/statements/`, { page_size: 500 }),
  })

/** After anything changes a client's books, everything about that client is stale, and so is the clients list. */
export function useInvalidateClient(id: string) {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: clientKeys.one(id) }),
      queryClient.invalidateQueries({ queryKey: clientKeys.all }),
    ])
}

export function useCreateClient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: ClientRequest) => data(await api.POST('/api/v1/clients/', { body })) as unknown as Client,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: clientKeys.all }),
  })
}

export function useUpdateClient(id: string) {
  const invalidate = useInvalidateClient(id)
  return useMutation({
    mutationFn: async (body: components['schemas']['PatchedClientRequest']) =>
      data(await api.PATCH('/api/v1/clients/{id}/', { params: { path: { id } }, body })) as unknown as Client,
    onSuccess: invalidate,
  })
}
