// The financial year in view, as a menu. Used by the context bar and by the phone's drawer.

import { Listbox } from '@/components/ui/listbox'
import { useNavigate, useRouterState, useSearch } from '@tanstack/react-router'
import { ChevronRight } from 'lucide-react'
import { fyLabel, financialYearOf } from '@/lib/format'
import { parseFy } from '@/lib/fy'
import { moduleOf, type ModuleId } from '@/lib/modules'
import { cn } from '@/lib/utils'
import { useFy } from './useFy'

/** Modules where the financial year in view means something under All clients. */
const FY_MODULES: ModuleId[] = ['dashboard', 'clients', 'pipeline', 'bookkeeping', 'bank', 'gst', 'reports']

/**
 * The financial year in view (April to March, named by the year it starts in). Inside a client it is
 * that client's remembered year, written to `?fy=`. Under All clients it is a firm-level year, also
 * carried in `?fy=`, and picking a client afterwards keeps it.
 */
export function FySelect({ className, crumb = false }: { className?: string; crumb?: boolean }) {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const { clientId, fy: clientFy, setFy: setClientFy, dataYears } = useFy()
  const search = useSearch({ strict: false }) as { fy?: unknown }
  const navigate = useNavigate()
  const module = moduleOf(path)
  if (!clientId && (!module || !FY_MODULES.includes(module))) return null

  const now = financialYearOf(new Date())
  const fy = clientId ? clientFy : (parseFy(search.fy) ?? now)
  const setFy = clientId
    ? setClientFy
    : (next: number) => void navigate({ to: '.', search: ((prev: Record<string, unknown>) => ({ ...prev, fy: next })) as never, replace: true })
  // A year that has not begun has no books to show, so the list starts at the current one.
  const years = new Set([...Array.from({ length: 8 }, (_, i) => now - i), ...dataYears, fy])
  const list = (
    <Listbox
      aria-label="Financial year"
      value={String(fy)}
      onValueChange={(v) => setFy(Number(v))}
      options={[...years].sort((a, b) => b - a).map((year) => ({ value: String(year), label: `FY ${fyLabel(year)}` }))}
      className={cn(
        'h-9 w-auto shrink-0 gap-2 rounded-md px-2.5 text-sm font-medium',
        crumb ? 'min-w-0 border-transparent bg-transparent text-muted-foreground shadow-none hover:bg-hover hover:text-foreground dark:border-transparent dark:bg-transparent dark:hover:bg-hover' : 'min-w-32',
        className,
      )}
    />
  )
  return crumb ? (
    <>
      <ChevronRight className="size-3.5 shrink-0 text-faint" aria-hidden />
      {list}
    </>
  ) : (
    list
  )
}
