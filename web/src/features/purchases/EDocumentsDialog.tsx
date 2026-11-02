// The e-invoice and e-way bill JSON for a sales invoice, drafted from the books. What the books do not hold (addresses, pincodes, the
// distance and vehicle) is asked for here and the draft is refreshed; each file is downloaded to be uploaded to the portal. Nothing is sent.

import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { V1 } from '@/api/queries/clients'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { saveFile } from '@/platform/download'
import { toast } from '@/lib/toast'

interface Doc {
  json: unknown
  missing: string[]
  required?: boolean
}
interface Drafts {
  eligible: boolean
  note: string
  e_invoice: Doc | null
  eway_bill: Doc | null
}

const FIELDS: { key: string; label: string; width?: string }[] = [
  { key: 'seller_address', label: 'Your address', width: 'w-64' },
  { key: 'seller_place', label: 'Your place', width: 'w-36' },
  { key: 'seller_pin', label: 'Your pincode', width: 'w-28' },
  { key: 'buyer_address', label: 'Buyer address', width: 'w-64' },
  { key: 'buyer_place', label: 'Buyer place', width: 'w-36' },
  { key: 'buyer_pin', label: 'Buyer pincode', width: 'w-28' },
  { key: 'distance_km', label: 'Distance (km)', width: 'w-28' },
  { key: 'vehicle_no', label: 'Vehicle number', width: 'w-36' },
  { key: 'transporter_id', label: 'Transporter id', width: 'w-40' },
]

export function EDocumentsDialog({ clientId, billId, reference, onClose }: { clientId: string; billId: string; reference: string; onClose: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [drafts, setDrafts] = useState<Drafts | null>(null)
  const make = useMutation({
    mutationFn: (details: Record<string, string | number>) => raw.post<Drafts>(`${V1}/clients/${clientId}/bills/${billId}/e-documents/`, details),
    onSuccess: setDrafts,
    onError: (e) => toast.error(messageOf(e)),
  })
  useEffect(() => make.mutate({}), []) // eslint-disable-line react-hooks/exhaustive-deps

  function refresh() {
    const body: Record<string, string | number> = {}
    for (const [k, v] of Object.entries(values)) if (v.trim()) body[k] = k === 'distance_km' ? Number(v) : v.trim()
    make.mutate(body)
  }

  async function download(doc: Doc, name: string) {
    await saveFile(name, new Blob([JSON.stringify(doc.json, null, 2)], { type: 'application/json' }))
  }

  const section = (title: string, doc: Doc | null, file: string) =>
    doc && (
      <section aria-label={title} className="grid gap-1">
        <h3 className="font-medium">
          {title}
          {doc.required === true && <span className="ml-2 text-xs text-muted-foreground">needed: the invoice is over ₹50,000</span>}
        </h3>
        {doc.missing.length > 0 ? (
          <ul className="list-disc pl-5 text-xs">
            {doc.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">Nothing missing.</p>
        )}
        <div>
          <Button size="sm" variant="outline" onClick={() => void download(doc, file)}>
            Download {title} JSON
          </Button>
        </div>
      </section>
    )

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>E-invoice and e-way bill for {reference}</DialogTitle>
          <DialogDescription>Drafted from the books. Add what is missing, then download the files to upload to the portal. Nothing is sent from here.</DialogDescription>
        </DialogHeader>
        {drafts && !drafts.eligible && <p className="text-sm">{drafts.note}</p>}
        {drafts?.eligible && (
          <div className="grid gap-3 text-sm">
            <p className="text-xs text-muted-foreground">{drafts.note}</p>
            <div className="flex flex-wrap gap-2">
              {FIELDS.map((f) => (
                <label key={f.key} className="grid gap-0.5 text-xs text-muted-foreground">
                  <span aria-hidden>{f.label}</span>
                  <Input aria-label={f.label} className={f.width} value={values[f.key] ?? ''} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
                </label>
              ))}
            </div>
            <div>
              <Button size="sm" loading={make.isPending} onClick={refresh}>
                Update the draft
              </Button>
            </div>
            {section('E-invoice', drafts.e_invoice, `e-invoice-${reference}.json`)}
            {section('E-way bill', drafts.eway_bill, `eway-bill-${reference}.json`)}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
