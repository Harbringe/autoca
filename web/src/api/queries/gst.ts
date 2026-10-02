// GST reconciliation: the registrations a client holds, its runs, and one run's report.
//
// Every step that changes a run (upload, match, decide, sign off) answers with the whole report, so
// the answer is written straight into the run's cache entry instead of being fetched again.

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { GstReport, GstRegistration, GstRun, Page } from '@/api/types'
import { V1 } from './clients'

export const gstKeys = {
  registrations: (clientId: string) => ['client', clientId, 'gst', 'registrations'] as const,
  runs: (clientId: string) => ['client', clientId, 'gst', 'runs'] as const,
  run: (clientId: string, runId: string) => ['client', clientId, 'gst', 'run', runId] as const,
}

const base = (clientId: string) => `${V1}/clients/${clientId}/gst`

export const gstRegistrations = (clientId: string) =>
  queryOptions({
    queryKey: gstKeys.registrations(clientId),
    // Paginated on the wire; a client holds a handful of GSTINs, so one big page is the list.
    queryFn: async () => (await raw.get<Page<GstRegistration>>(`${base(clientId)}/registrations/`, { page_size: 100 })).results,
  })

export const gstRuns = (clientId: string) =>
  queryOptions({
    queryKey: gstKeys.runs(clientId),
    queryFn: () => raw.get<GstRun[]>(`${base(clientId)}/runs/`),
  })

export const gstRun = (clientId: string, runId: string) =>
  queryOptions({
    queryKey: gstKeys.run(clientId, runId),
    queryFn: () => raw.get<GstReport>(`${base(clientId)}/runs/${runId}/`),
  })

/** The GST screens' writes. Each returns the run's new report. */
export function useGstActions(clientId: string) {
  const queryClient = useQueryClient()
  const keep = (report: GstReport) => {
    queryClient.setQueryData(gstKeys.run(clientId, report.id), report)
    // The runs list shows each run's status; the firm landing shows the latest run per client.
    void queryClient.invalidateQueries({ queryKey: gstKeys.runs(clientId) })
    return report
  }

  return {
    addRegistration: useMutation({
      mutationFn: (body: { gstin: string; registration_type: 'regular' | 'composition' | 'other' }) =>
        raw.post<GstRegistration>(`${base(clientId)}/registrations/`, body),
      onSuccess: () => void queryClient.invalidateQueries({ queryKey: gstKeys.registrations(clientId) }),
    }),
    newRun: useMutation({
      mutationFn: (body: { registration: string; period: string }) => raw.post<GstReport>(`${base(clientId)}/runs/`, body),
      onSuccess: keep,
    }),
    upload: useMutation({
      mutationFn: async ({ runId, which, file }: { runId: string; which: 'register' | 'portal'; file: File }) => {
        const form = new FormData()
        form.set('file', file)
        return raw.post<{ rows: number; run: GstReport }>(`${base(clientId)}/runs/${runId}/${which}/`, form)
      },
      onSuccess: (result) => keep(result.run),
    }),
    match: useMutation({
      mutationFn: (runId: string) => raw.post<GstReport>(`${base(clientId)}/runs/${runId}/reconcile/`),
      onSuccess: keep,
    }),
    decide: useMutation({
      mutationFn: ({ runId, ...body }: { runId: string; match: string; kind: string; note: string }) =>
        raw.post<GstReport>(`${base(clientId)}/runs/${runId}/decisions/`, body),
      onSuccess: keep,
    }),
    signOff: useMutation({
      mutationFn: (runId: string) => raw.post<GstReport>(`${base(clientId)}/runs/${runId}/sign-off/`),
      onSuccess: keep,
    }),
  }
}

/** The Excel working paper. Returns the file and the name the server gave it. */
export const gstExport = (clientId: string, runId: string) => raw.blob(`${base(clientId)}/runs/${runId}/export/`)
