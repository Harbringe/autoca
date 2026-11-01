// Voucher number formats: for each series (a standard voucher type, or one of the firm's own) a prefix and how many digits to pad to,
// with the next number shown as it will read. Only what is shown changes; the numbers in the books stay as they are.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { numbering, useSaveNumbering, type NumberingSeries } from '@/api/queries/numbering'
import { ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useFy } from '@/features/shell/useFy'
import { toast } from '@/lib/toast'

const key = (s: Pick<NumberingSeries, 'voucher_type' | 'type_name'>) => `${s.voucher_type}|${s.type_name}`
const nameOf = (s: NumberingSeries) => s.type_name || s.voucher_type

export function NumberingSettings({ clientId, mayEdit }: { clientId: string; mayEdit: boolean }) {
  const { fy } = useFy()
  const list = useQuery(numbering(clientId, fy))
  const save = useSaveNumbering(clientId, fy)
  const [edits, setEdits] = useState<Record<string, { prefix: string; padding: number }>>({})

  if (list.isPending) return <Spinner />
  if (list.error) return <ErrorState error={list.error} retry={() => void list.refetch()} />

  const valueOf = (s: NumberingSeries) => edits[key(s)] ?? { prefix: s.prefix, padding: s.padding }
  const changed = list.data.filter((s) => {
    const v = valueOf(s)
    return v.prefix !== s.prefix || v.padding !== s.padding
  })

  async function submit() {
    try {
      await save.mutateAsync(changed.map((s) => ({ voucher_type: s.voucher_type, type_name: s.type_name, ...valueOf(s) })))
      setEdits({})
      toast.success('Number formats saved')
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : 'Something went wrong. Try again.')
    }
  }

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Voucher number formats</h2>
      <p className="text-sm text-muted-foreground">
        How each series' numbers read, for example <span className="num">S/&#123;fy&#125;/0001</span>. Only the look changes; the numbers in the books stay as they are.
      </p>
      <ul aria-label="Voucher series" className="divide-y divide-border-strong rounded-lg border border-border-strong text-sm">
        {list.data.map((s) => {
          const v = valueOf(s)
          return (
            <li key={key(s)} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2">
              <span className="min-w-36 flex-1 font-medium">
                {nameOf(s)}
                {s.type_name ? <span className="font-normal text-muted-foreground"> (as {s.voucher_type})</span> : null}
              </span>
              <Input
                aria-label={`Prefix for ${nameOf(s)}`}
                className="w-36"
                maxLength={16}
                value={v.prefix}
                disabled={!mayEdit}
                onChange={(e) => setEdits((c) => ({ ...c, [key(s)]: { ...v, prefix: e.target.value } }))}
              />
              <Input
                aria-label={`Digits for ${nameOf(s)}`}
                className="w-20"
                type="number"
                min={0}
                max={8}
                value={v.padding}
                disabled={!mayEdit}
                onChange={(e) => setEdits((c) => ({ ...c, [key(s)]: { ...v, padding: Number(e.target.value) } }))}
              />
              <span data-testid={`example-${s.voucher_type}-${s.type_name}`} className="num w-28 text-right text-muted-foreground">
                {s.example}
              </span>
            </li>
          )
        })}
      </ul>
      {mayEdit && (
        <div>
          <Button loading={save.isPending} disabled={changed.length === 0} onClick={() => void submit()}>
            Save number formats
          </Button>
        </div>
      )}
    </Card>
  )
}
