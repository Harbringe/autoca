// A cheque leaf: the date in boxes, the payee, the amount in words and figures, an optional A/C Payee crossing and the client's
// signature line. Laid out for a standard 203 x 90 mm leaf; banks differ a little, so the print can be moved a few millimetres.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { cheque } from '@/api/queries/cheques'
import { clientDetail } from '@/api/queries/clients'
import { ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { amountInWords } from '@/lib/amountInWords'
import { formatPaise } from '@/lib/format'

export function ChequePrint({ clientId, chequeId }: { clientId: string; chequeId: string }) {
  const q = useQuery(cheque(clientId, chequeId))
  const client = useQuery(clientDetail(clientId))
  const [crossed, setCrossed] = useState(true)
  const [dx, setDx] = useState(0)
  const [dy, setDy] = useState(0)
  if (q.isPending) return <Spinner />
  if (q.error) return <ErrorState error={q.error} retry={() => void q.refetch()} />
  const c = q.data
  const [y, m, d] = c.cheque_date.split('-')
  const digits = `${d}${m}${y}`.split('')

  return (
    <div className="mx-auto grid max-w-[210mm] gap-3">
      <div className="no-print flex flex-wrap items-center justify-end gap-3">
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={crossed} onChange={(e) => setCrossed(e.target.checked)} /> A/C Payee only
        </label>
        <label className="flex items-center gap-1 text-sm">
          Move right (mm)
          <input aria-label="Move right (mm)" type="number" className="h-8 w-16 rounded border px-1" value={dx} onChange={(e) => setDx(Number(e.target.value) || 0)} />
        </label>
        <label className="flex items-center gap-1 text-sm">
          Move down (mm)
          <input aria-label="Move down (mm)" type="number" className="h-8 w-16 rounded border px-1" value={dy} onChange={(e) => setDy(Number(e.target.value) || 0)} />
        </label>
        <Button variant="outline" onClick={() => window.history.back()}>
          Back
        </Button>
        <Button onClick={() => window.print()}>Print</Button>
      </div>
      <article aria-label={`Cheque ${c.number}`} className="print-sheet relative h-[90mm] w-[203mm] max-w-full overflow-hidden border border-border-strong bg-white text-black">
        <div className="absolute inset-0" style={{ transform: `translate(${dx}mm, ${dy}mm)` }}>
          {crossed && (
            <div className="absolute left-[12mm] top-[8mm] -rotate-6 border-y-2 border-black px-2 text-xs font-bold leading-tight" aria-label="Crossing">
              A/C PAYEE
            </div>
          )}
          <div className="absolute right-[10mm] top-[6mm] flex" aria-label="Date">
            {digits.map((ch, i) => (
              <span key={i} className="grid h-[7mm] w-[6mm] place-items-center border border-black text-sm font-medium">
                {ch}
              </span>
            ))}
          </div>
          <div className="absolute left-[24mm] top-[24mm] w-[150mm] border-b border-dotted border-black pb-0.5 text-base" aria-label="Payee">
            {c.print_name}
          </div>
          <div className="absolute left-[24mm] top-[36mm] w-[130mm] text-sm leading-snug" aria-label="Amount in words">
            {amountInWords(c.amount_paise)}
          </div>
          <div className="absolute right-[10mm] top-[44mm] border-2 border-black px-3 py-1 text-lg font-semibold tabular-nums" aria-label="Amount in figures">
            ₹ {formatPaise(c.amount_paise, { symbol: false })}/-
          </div>
          <div className="absolute bottom-[8mm] right-[10mm] w-[70mm] border-t border-black pt-0.5 text-center text-xs">For {client.data?.name ?? ''}</div>
        </div>
      </article>
      <p className="no-print text-xs text-muted-foreground">Print at 100% (no scaling) on the cheque leaf. Try a plain sheet first and hold it against a leaf to line it up; use the two moves above to correct it.</p>
    </div>
  )
}
