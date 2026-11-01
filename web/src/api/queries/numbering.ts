// How each of a client's voucher series reads its numbers (a prefix and zero padding). The stored numbers never change.

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { V1 } from './clients'

export interface NumberingSeries {
  voucher_type: string
  type_name: string
  prefix: string
  padding: number
  /** The next number in this series, as it will read. */
  example: string
}

const path = (clientId: string, fy: number) => `${V1}/clients/${clientId}/numbering/?fy=${fy}`

export const numbering = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: ['numbering', clientId, fy],
    queryFn: () => raw.get<NumberingSeries[]>(path(clientId, fy)),
  })

/** Save the series whose format was changed; the answer is every series again, with fresh examples. */
export function useSaveNumbering(clientId: string, fy: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changed: Omit<NumberingSeries, 'example'>[]) => raw.put<NumberingSeries[]>(path(clientId, fy), changed),
    onSuccess: (fresh) => {
      queryClient.setQueryData(numbering(clientId, fy).queryKey, fresh)
      // Day Book and ledgers show numbers in this format, so they are read again.
      void queryClient.invalidateQueries({ queryKey: ['client', clientId] })
    },
  })
}
