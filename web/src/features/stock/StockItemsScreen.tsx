// The client's stock items: name, unit, HSN, GST rate and reorder level, kept tidy by a person. Purchases and sales name the same items
// on their invoice lines, so what is kept here is what the stock report and the invoice forms agree on.

import { useQuery } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { stockItems, useChangeStockItem, useMakeStockItem, useRemoveStockItem, type StockItem, type StockItemInput } from '@/api/queries/stockItems'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Confirm } from '@/components/ca/Confirm'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { toast } from '@/lib/toast'
import { GodownsCard } from './GodownsCard'
import { say } from './say'
import { ManufacturingCard } from './ManufacturingCard'
import { StockCountCard } from './StockCountCard'
import { StockMoveCard } from './StockMoveCard'
import { StockTallyImportCard } from './StockTallyImportCard'

/** "5.00" is shown as "5", "20.000" as "20": the stored figures carry zeros nobody writes. */
const plain = (value: string | null) => (value === null || value === '' ? '' : String(Number(value)))

interface Fields {
  name: string
  unit: string
  hsn_sac: string
  gst_rate: string
  reorder_level: string
  /** Other names the item goes by on invoices, separated by semicolons. */
  aliases: string
}
const EMPTY: Fields = { name: '', unit: '', hsn_sac: '', gst_rate: '', reorder_level: '', aliases: '' }

/** Only what was filled in: an empty box is left out on adding, and clears the figure on a change. */
function toInput(f: Fields, clearing: boolean): StockItemInput {
  const out: StockItemInput = { name: f.name.trim(), unit: f.unit.trim() }
  if (f.hsn_sac.trim() || clearing) out.hsn_sac = f.hsn_sac.trim()
  if (f.gst_rate.trim() || clearing) out.gst_rate = f.gst_rate.trim() || null
  if (f.reorder_level.trim() || clearing) out.reorder_level = f.reorder_level.trim() || null
  if (f.aliases.trim() || clearing) out.aliases = f.aliases.split(';').map((a) => a.trim()).filter(Boolean)
  return out
}

/** `about` names the item being changed, so its boxes are told apart from the ones that add a new item. */
function FieldsRow({ f, set, idPrefix, about }: { f: Fields; set: (next: Fields) => void; idPrefix: string; about?: string }) {
  const field = (key: keyof Fields, label: string, className: string, extra: Record<string, string> = {}) => (
    <label className="grid gap-0.5 text-xs text-muted-foreground">
      <span aria-hidden>{label}</span>
      <Input id={`${idPrefix}-${key}`} aria-label={about ? `${label} of ${about}` : label} className={className} value={f[key]} onChange={(e) => set({ ...f, [key]: e.target.value })} {...extra} />
    </label>
  )
  return (
    <>
      {field('name', 'Item name', 'w-56')}
      {field('unit', 'Unit', 'w-20', { maxLength: '16' })}
      {field('hsn_sac', 'HSN', 'w-24', { maxLength: '8' })}
      {field('gst_rate', 'GST %', 'w-20', { inputMode: 'decimal' })}
      {field('reorder_level', 'Reorder level', 'w-28', { inputMode: 'decimal' })}
      {field('aliases', 'Also called (separate with ;)', 'w-64')}
    </>
  )
}

export function StockItemsScreen({ clientId, mayEdit }: { clientId: string; mayEdit: boolean }) {
  const items = useQuery(stockItems(clientId))
  const make = useMakeStockItem(clientId)
  const change = useChangeStockItem(clientId)
  const remove = useRemoveStockItem(clientId)
  const [adding, setAdding] = useState<Fields>(EMPTY)
  const [editing, setEditing] = useState<{ id: string; fields: Fields } | null>(null)
  const [removing, setRemoving] = useState<StockItem | null>(null)

  async function add() {
    try {
      await make.mutateAsync(toInput(adding, false))
      setAdding(EMPTY)
      toast.success('Item added')
    } catch (e) {
      toast.error(say(e))
    }
  }

  async function save() {
    if (!editing) return
    try {
      await change.mutateAsync({ id: editing.id, input: toInput(editing.fields, true) })
      setEditing(null)
    } catch (e) {
      toast.error(say(e))
    }
  }

  if (items.isPending) return <Spinner />
  if (items.error) return <ErrorState error={items.error} retry={() => void items.refetch()} />

  return (
    <div className="grid gap-3">
      <Card className="grid gap-3 p-4">
        <h2 className="font-medium">Stock items</h2>
        <p className="text-sm text-muted-foreground">
          The products this client buys and sells. Invoices that list items add to this list on their own; keep the unit, HSN, GST rate and reorder level
          here.
        </p>
        {items.data.length === 0 ? (
          <EmptyState title="No stock items yet">Items are added here as invoices with item lines are booked, or you can add one below.</EmptyState>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-strong">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-strong text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Item</th>
                  <th className="px-3 py-2 font-medium">Unit</th>
                  <th className="px-3 py-2 font-medium">HSN</th>
                  <th className="px-3 py-2 text-right font-medium">GST rate</th>
                  <th className="px-3 py-2 text-right font-medium">Reorder level</th>
                  {mayEdit && <th className="px-3 py-2" />}
                </tr>
              </thead>
              <tbody>
                {items.data.map((item) =>
                  editing?.id === item.id ? (
                    <tr key={item.id} className="border-b border-border-strong last:border-0">
                      <td className="px-3 py-2" colSpan={mayEdit ? 6 : 5}>
                        <div className="flex flex-wrap items-end gap-2">
                          <FieldsRow f={editing.fields} set={(fields) => setEditing({ id: item.id, fields })} idPrefix={`edit-${item.id}`} about={item.name} />
                          <Button loading={change.isPending} onClick={() => void save()}>
                            Save
                          </Button>
                          <Button variant="ghost" onClick={() => setEditing(null)}>
                            Cancel
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    <tr key={item.id} aria-label={item.name} className="border-b border-border-strong last:border-0">
                      <td className="px-3 py-2 font-medium">
                        {item.name}
                        {(item.aliases ?? []).length > 0 && <span className="block text-xs font-normal text-muted-foreground">Also: {(item.aliases ?? []).join('; ')}</span>}
                      </td>
                      <td className="px-3 py-2">{item.unit}</td>
                      <td className="px-3 py-2">{item.hsn_sac}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{item.gst_rate ? `${plain(item.gst_rate)}%` : ''}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{plain(item.reorder_level)}</td>
                      {mayEdit && (
                        <td className="whitespace-nowrap px-3 py-2 text-right">
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={`Edit ${item.name}`}
                            onClick={() =>
                              setEditing({
                                id: item.id,
                                fields: { name: item.name, unit: item.unit, hsn_sac: item.hsn_sac, gst_rate: plain(item.gst_rate), reorder_level: plain(item.reorder_level), aliases: (item.aliases ?? []).join('; ') },
                              })
                            }
                          >
                            <Pencil />
                          </Button>
                          <Button size="sm" variant="ghost" aria-label={`Remove ${item.name}`} onClick={() => setRemoving(item)}>
                            <Trash2 />
                          </Button>
                        </td>
                      )}
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
        {mayEdit && (
          <div className="flex flex-wrap items-end gap-2">
            <FieldsRow f={adding} set={setAdding} idPrefix="add" />
            <Button loading={make.isPending} disabled={!adding.name.trim()} onClick={() => void add()}>
              Add item
            </Button>
          </div>
        )}
      </Card>

      {mayEdit && <StockTallyImportCard clientId={clientId} />}
      <GodownsCard clientId={clientId} mayEdit={mayEdit} />
      {mayEdit && <StockMoveCard clientId={clientId} />}
      {mayEdit && <StockCountCard clientId={clientId} />}
      <ManufacturingCard clientId={clientId} mayEdit={mayEdit} />

      <Confirm
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove this stock item?"
        confirmLabel="Remove item"
        destructive
        onConfirm={async () => {
          if (removing) await remove.mutateAsync(removing.id)
        }}
      >
        {removing ? `${removing.name} is taken off the list. Invoices that already name it are not changed.` : null}
      </Confirm>
    </div>
  )
}
