import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useCallback, useEffect } from 'react'
import { journal } from '@/api/queries/books'
import { statements } from '@/api/queries/clients'
import { financialYearOf } from '@/lib/format'
import { parseFy, resolveFy } from '@/lib/fy'
import { usePreferences } from '@/lib/preferences'
import { useSession } from '@/session/session'

/**
 * The financial year on screen for the client in the URL, and how to change it. Choosing a year
 * is remembered for that client and written to `?fy=`, so the address of a report opens that year.
 */
export function useFy() {
  const { can } = useSession()
  const { clientId } = useParams({ strict: false }) as { clientId?: string }
  const search = useSearch({ strict: false }) as { fy?: unknown }
  const navigate = useNavigate()
  const { fyByClient, setClientFy } = usePreferences()

  const stmts = useQuery({ ...statements(clientId ?? ''), enabled: !!clientId && can('document.view') })
  const entries = useQuery({ ...journal(clientId ?? ''), enabled: !!clientId && can('report.view') })

  const dataYears = [
    ...new Set([
      ...(stmts.data?.results ?? []).flatMap((s) => [financialYearOf(s.period_start), financialYearOf(s.period_end)]),
      ...(entries.data ?? []).map((e) => e.financial_year),
    ]),
  ].sort()

  const fromUrl = parseFy(search.fy)
  const remembered = clientId ? parseFy(fyByClient[clientId]) : undefined
  const { fy, explicit } = resolveFy({ fromUrl, remembered, dataYears, current: financialYearOf(new Date()) })
  // The default cannot be known until the client's statements and vouchers have arrived.
  const ready = explicit || !(stmts.isLoading || entries.isLoading)

  // A link that names a year is a choice: keep it when the person moves to another tab.
  useEffect(() => {
    if (clientId && fromUrl !== undefined) setClientFy(clientId, fromUrl)
  }, [clientId, fromUrl, setClientFy])

  const setFy = useCallback(
    (next: number) => {
      if (!clientId) return
      setClientFy(clientId, next)
      void navigate({ search: ((prev: Record<string, unknown>) => ({ ...prev, fy: next })) as never, replace: true })
    },
    [clientId, navigate, setClientFy],
  )

  return { clientId, fy, setFy, explicit, ready, dataYears }
}
