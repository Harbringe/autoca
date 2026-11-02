// Does the stock register agree with the books, the bills and the item list? Reads only; each line says what to do.

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { stockReconciliation } from '@/api/queries/books'
import { formatPaise } from '@/lib/format'

export function StockReconciliationCard({ clientId, fy }: { clientId: string; fy: number }) {
  const query = useQuery(stockReconciliation(clientId, fy))
  if (!query.data) return null
  const data = query.data
  const open = data.checks.filter((c) => c.status !== 'ok')

  return (
    <section aria-label="Stock against the books" className="mb-4 rounded-md border border-line p-3 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-medium">Stock against the books</h3>
        <span className="text-xs text-gray-600">
          Register {formatPaise(data.register_value_paise)} · Books {formatPaise(data.books_value_paise)}
          {data.difference_paise !== 0 && <> · Difference {formatPaise(data.difference_paise)}</>}
        </span>
      </div>
      {data.agrees && open.length === 0 ? (
        <p className="mt-2 flex items-center gap-2">
          <CheckCircle2 className="size-4 shrink-0" aria-hidden /> The register, the books and the item list agree.
        </p>
      ) : (
        <ul className="mt-2 grid gap-2">
          {open.map((c) => (
            <li key={c.key} className="flex gap-2">
              {c.status === 'attention' ? <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden /> : <Info className="mt-0.5 size-4 shrink-0" aria-hidden />}
              <span>
                <strong>{c.title}.</strong> {c.message}
                {c.examples.length > 0 && <span className="text-gray-600"> {c.examples.join('; ')}.</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
