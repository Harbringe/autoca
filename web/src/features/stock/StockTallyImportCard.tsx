// Bring the client's stock items in from Tally's stock-item export: read the file, show what would happen to each item and its opening
// stock, and write them only when the person says so. Safe to repeat: an item already kept is only filled in where it is blank.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { useRef, useState } from 'react'
import { raw } from '@/api/client'
import { V1 } from '@/api/queries/clients'
import { useInvalidateClient } from '@/api/queries/clients'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useFy } from '@/features/shell/useFy'
import { formatPaise, plural } from '@/lib/format'
import { toast } from '@/lib/toast'
import { say } from './say'

interface Row {
  name: string
  unit: string
  opening_qty: string
  opening_value_paise: number
  item: 'new' | 'fill' | 'same'
  opening: 'add' | 'exists' | 'sealed' | 'none'
  reason: string
}
interface Result {
  applied: boolean
  rows: Row[]
  counts: { new: number; filled: number; same: number; opening_added: number; opening_skipped: number }
}

const ITEM_WORDS: Record<Row['item'], string> = { new: 'New item', fill: 'Blanks filled in', same: 'Already kept' }
const OPENING_WORDS: Record<Row['opening'], string> = { add: 'Opening stock added', exists: 'Opening stock left as it is', sealed: 'Not added: books sealed', none: '' }

export function StockTallyImportCard({ clientId }: { clientId: string }) {
  const { fy } = useFy()
  const queryClient = useQueryClient()
  const invalidate = useInvalidateClient(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Result | null>(null)

  const send = useMutation({
    mutationFn: ({ file, apply }: { file: File; apply: boolean }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('financial_year', String(fy))
      form.append('apply', String(apply))
      return raw.post<Result>(`${V1}/clients/${clientId}/stock-items/import-tally/`, form)
    },
  })

  async function read(chosen: File) {
    setFile(chosen)
    setPreview(null)
    try {
      setPreview(await send.mutateAsync({ file: chosen, apply: false }))
    } catch (e) {
      setFile(null)
      toast.error(say(e))
    }
  }

  async function bringIn() {
    if (!file) return
    try {
      const done = await send.mutateAsync({ file, apply: true })
      await invalidate()
      await queryClient.invalidateQueries({ queryKey: ['stock-items', clientId] })
      toast.success(
        `${plural(done.counts.new, 'new item')}, ${plural(done.counts.filled, 'item')} filled in, opening stock added for ${done.counts.opening_added}.`,
      )
      setFile(null)
      setPreview(null)
    } catch (e) {
      toast.error(say(e))
    }
  }

  const todo = preview ? preview.rows.filter((r) => r.item !== 'same' || r.opening === 'add').length : 0

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Bring items in from Tally</h2>
      <p className="text-sm text-muted-foreground">
        Choose the stock items exported from Tally (Masters, Stock Items, as .xml or .json). Nothing is written until you have seen what would happen. Opening
        stock is dated 1 April {fy} (FY {fy}-{String(fy + 1).slice(2)}); an item already on this list is only filled in where it is blank.
      </p>
      <div>
        <input
          ref={input}
          type="file"
          accept=".xml,.json,text/xml,application/json"
          className="hidden"
          onChange={(e) => {
            const chosen = e.target.files?.[0]
            if (chosen) void read(chosen)
            e.target.value = ''
          }}
        />
        <Button variant="outline" loading={send.isPending && !preview} onClick={() => input.current?.click()}>
          <FileUp /> Choose the stock items file
        </Button>
      </div>
      {preview && (
        <div className="grid gap-3">
          <div className="overflow-x-auto rounded-lg border border-border-strong">
            <table className="w-full text-sm" aria-label="Stock items found in the file">
              <thead>
                <tr className="border-b border-border-strong text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Item</th>
                  <th className="px-3 py-2 font-medium">Unit</th>
                  <th className="px-3 py-2 text-right font-medium">Opening quantity</th>
                  <th className="px-3 py-2 text-right font-medium">Opening value</th>
                  <th className="px-3 py-2 font-medium">What happens</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.name} className="border-b border-border-strong last:border-0">
                    <td className="px-3 py-2 font-medium">{r.name}</td>
                    <td className="px-3 py-2">{r.unit}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.opening_qty === '0' ? '' : r.opening_qty}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.opening_value_paise ? formatPaise(r.opening_value_paise, { symbol: false }) : ''}</td>
                    <td className="px-3 py-2">
                      {ITEM_WORDS[r.item]}
                      {OPENING_WORDS[r.opening] ? ` · ${OPENING_WORDS[r.opening]}` : ''}
                      {r.reason ? <span className="block text-xs text-muted-foreground">{r.reason}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button loading={send.isPending} disabled={todo === 0} onClick={() => void bringIn()}>
              Bring in {plural(todo, 'item')}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setFile(null)
                setPreview(null)
              }}
            >
              Cancel
            </Button>
            {todo === 0 && <span className="text-sm text-muted-foreground">Everything in this file is already here.</span>}
          </div>
        </div>
      )}
    </Card>
  )
}
