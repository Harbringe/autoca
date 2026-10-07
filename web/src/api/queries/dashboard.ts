// The reporting dashboards. The portfolio is keyed under ['clients'] so a post, a seal or a lead change
// refreshes it with the rest of the firm; a client's snapshot is keyed under that client for the same reason.

import { queryOptions } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { ClientSnapshot, MyWork, PeopleWork, Portfolio, WorkFlow } from '@/api/types'
import { clientKeys, V1 } from './clients'

export const portfolio = () =>
  queryOptions({
    queryKey: ['clients', 'portfolio'],
    queryFn: () => raw.get<Portfolio>(`${V1}/firm/portfolio/`),
    staleTime: 30_000,
  })

export const clientSnapshot = (id: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(id, 'snapshot', fy),
    queryFn: () => raw.get<ClientSnapshot>(`${V1}/clients/${id}/dashboard/?fy=${fy}`),
    staleTime: 30_000,
  })

/** Weekly received against finished. The server scopes it to the caller's clients, whatever is asked. */
export const workFlow = (range?: { from: string; to: string }) =>
  queryOptions({
    queryKey: ['firm', 'work-flow', range?.from ?? null, range?.to ?? null],
    queryFn: () => raw.get<WorkFlow>(`${V1}/firm/work-flow/`, range ? { from: range.from, to: range.to } : undefined),
    retry: false,
    staleTime: 30_000,
  })

/** What each person has on. Administrators and Senior CAs only: callers must not ask for anyone else (it is a 403). */
export const firmPeople = (range?: { from: string; to: string }) =>
  queryOptions({
    queryKey: ['firm', 'people', range?.from ?? null, range?.to ?? null],
    queryFn: () => raw.get<PeopleWork>(`${V1}/firm/people/`, range ? { from: range.from, to: range.to } : undefined),
    retry: false,
    staleTime: 30_000,
  })

/** The signed-in person's own work: counts, daily finished, the next tasks and their clients. */
export const myWork = (range?: { from: string; to: string }) =>
  queryOptions({
    queryKey: ['clients', 'my-work', range?.from ?? null, range?.to ?? null],
    queryFn: () => raw.get<MyWork>(`${V1}/me/work/`, range ? { from: range.from, to: range.to } : undefined),
    staleTime: 30_000,
  })
