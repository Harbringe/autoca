// Voucher classes: presets for sales and purchase vouchers. Choosing one on the voucher form fills in the ledger and the GST rate; the
// person can still change both, and nothing posts differently.

import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { ledgers as ledgersQuery } from '@/api/queries/books'
import { useMakeVoucherClass, useRemoveVoucherClass, voucherClasses } from '@/api/queries/voucherClasses'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { toast } from '@/lib/toast'

const say = (e: unknown) => (e instanceof Error && e.message ? e.message : 'Something went wrong. Try again.')

export function VoucherClassesSettings({ clientId, mayEdit }: { clientId: string; mayEdit: boolean }) {
  const classes = useQuery(voucherClasses(clientId))
  const ledgers = useQuery(ledgersQuery(clientId))
  const make = useMakeVoucherClass(clientId)
  const remove = useRemoveVoucherClass(clientId)
  const [name, setName] = useState('')
  const [type, setType] = useState<'Sales' | 'Purchase'>('Sales')
  const [ledger, setLedger] = useState('')
  const [rate, setRate] = useState('')

  const usable = (ledgers.data ?? []).filter((l) => l.status === 'ACTIVE' && l.is_active)

  async function add() {
    try {
      await make.mutateAsync({ name: name.trim(), voucher_type: type, head_ledger: ledger, ...(rate.trim() ? { gst_rate: rate.trim() } : {}) })
      setName('')
      setRate('')
      toast.success('Class added')
    } catch (e) {
      toast.error(say(e))
    }
  }

  async function drop(id: string) {
    try {
      await remove.mutateAsync(id)
    } catch (e) {
      toast.error(say(e))
    }
  }

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Voucher classes</h2>
      <p className="text-sm text-muted-foreground">
        A preset for sales or purchase vouchers: choosing it on the voucher form fills in the ledger and the GST rate. You can still change both.
      </p>
      {(classes.data ?? []).length > 0 && (
        <ul aria-label="Voucher classes" className="divide-y divide-border-strong rounded-lg border border-border-strong text-sm">
          {(classes.data ?? []).map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span>
                <span className="font-medium">{c.name}</span>{' '}
                <span className="text-muted-foreground">
                  {c.voucher_type} · {c.head_ledger_name}
                  {c.gst_rate ? ` · ${c.gst_rate}%` : ''}
                </span>
              </span>
              {mayEdit && (
                <Button size="sm" variant="ghost" aria-label={`Remove ${c.name}`} onClick={() => void drop(c.id)}>
                  <Trash2 />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {mayEdit && (
        <div className="flex flex-wrap items-end gap-2">
          <Input aria-label="Class name" placeholder="Name, e.g. Retail 18%" className="w-48" value={name} onChange={(e) => setName(e.target.value)} />
          <Select aria-label="Class is for" value={type} onChange={(e) => setType(e.target.value as 'Sales' | 'Purchase')}>
            <option value="Sales">Sales</option>
            <option value="Purchase">Purchase</option>
          </Select>
          <Select aria-label="Class ledger" value={ledger} onChange={(e) => setLedger(e.target.value)}>
            <option value="">Ledger…</option>
            {usable.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
          <Input aria-label="Class GST rate" placeholder="GST %" className="w-24" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
          <Button loading={make.isPending} disabled={!name.trim() || !ledger} onClick={() => void add()}>
            Add class
          </Button>
        </div>
      )}
    </Card>
  )
}
