// A bank payment file from what the client owes: pick who to pay and how much, save where each party is paid, and download the file.
// Nothing is booked; the payment shows up on the bank statement once the bank has made it.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { messageOf } from '@/api/errors'
import { chequeAccounts } from '@/api/queries/cheques'
import { payables, useMakePaymentFile, useSavePaymentDetails, type Payable } from '@/api/queries/paymentFiles'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatPaise, parseRupees } from '@/lib/format'
import { saveFile } from '@/platform/download'
import { toast } from '@/lib/toast'

const money = (paise: number) => formatPaise(paise, { symbol: false })

function Details({ clientId, row, onSaved }: { clientId: string; row: Payable; onSaved: () => void }) {
  const save = useSavePaymentDetails(clientId)
  const [account, setAccount] = useState('')
  const [ifsc, setIfsc] = useState('')
  const [name, setName] = useState(row.name)
  return (
    <div className="flex flex-wrap items-end gap-2 pl-6" role="group" aria-label={`Bank details of ${row.name}`}>
      <Input aria-label={`Account number of ${row.name}`} className="w-48" placeholder={row.account_last4 ? `Account ••••${row.account_last4}` : 'Account number'} value={account} onChange={(e) => setAccount(e.target.value)} />
      <Input aria-label={`IFSC of ${row.name}`} className="w-32" placeholder="IFSC" value={ifsc} onChange={(e) => setIfsc(e.target.value)} />
      <Input aria-label={`Account name of ${row.name}`} className="w-56" placeholder="Name at the bank" value={name} onChange={(e) => setName(e.target.value)} />
      <Button
        size="sm"
        variant="outline"
        disabled={save.isPending || !account.trim() || !ifsc.trim() || !name.trim()}
        onClick={() => save.mutate({ party: row.party, account_number: account, ifsc, account_name: name }, { onSuccess: () => { setAccount(''); toast.success('Saved'); onSaved() }, onError: (e) => toast.error(messageOf(e)) })}
      >
        Save details
      </Button>
    </div>
  )
}

export function PaymentFileCard({ clientId }: { clientId: string }) {
  const owed = useQuery(payables(clientId))
  const accounts = useQuery(chequeAccounts(clientId))
  const make = useMakePaymentFile(clientId)
  const [picked, setPicked] = useState<Record<string, string>>({})
  const [open, setOpen] = useState<string | null>(null)
  const [mode, setMode] = useState<'NEFT' | 'RTGS' | 'IMPS'>('NEFT')
  const [date, setDate] = useState(new Date(Date.now() + 86_400_000).toISOString().slice(0, 10))
  const [account, setAccount] = useState('')
  const chosen = account || accounts.data?.[0]?.id || ''
  if (!owed.data || owed.data.length === 0) return null

  function build() {
    const items: { party: string; amount_paise: number }[] = []
    for (const [party, text] of Object.entries(picked)) {
      const paise = parseRupees(text)
      if (paise === null || paise <= 0) return void toast.error('Each amount is in rupees, like 25000 or 25000.50.')
      items.push({ party, amount_paise: paise })
    }
    if (items.length === 0) return void toast.error('Tick at least one party to pay.')
    make.mutate(
      { bank_account: chosen, mode, payment_date: date, items },
      {
        onSuccess: async ({ blob, filename }) => {
          await saveFile(filename ?? `payments-${date}.csv`, blob)
          toast.success('Payment file ready. It holds full account numbers, so keep it safe.')
        },
        onError: (e) => toast.error(messageOf(e)),
      },
    )
  }

  return (
    <section aria-label="Bank payment file" className="grid gap-2 rounded-md border border-line p-3 text-sm">
      <h2 className="text-[15px] font-semibold text-heading">Bank payment file</h2>
      <p className="text-muted-foreground">Tick the parties to pay and change an amount if paying part. Each needs bank details saved. Nothing is booked.</p>
      <ul className="grid gap-1">
        {owed.data.map((p) => (
          <li key={p.party} className="grid gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="checkbox"
                aria-label={`Pay ${p.name}`}
                checked={p.party in picked}
                onChange={(e) => {
                  const next = { ...picked }
                  if (e.target.checked) next[p.party] = String(p.open_paise / 100)
                  else delete next[p.party]
                  setPicked(next)
                }}
              />
              <span className="w-56">{p.name}</span>
              <span className="w-32 tabular-nums text-muted-foreground">owed {money(p.open_paise)}</span>
              {p.party in picked && <Input aria-label={`Amount for ${p.name}`} inputMode="decimal" className="w-32" value={picked[p.party]} onChange={(e) => setPicked({ ...picked, [p.party]: e.target.value })} />}
              <span>{p.ready ? `Account ••••${p.account_last4}` : 'No bank details'}</span>
              <Button size="sm" variant="ghost" onClick={() => setOpen(open === p.party ? null : p.party)}>
                {p.ready ? 'Change details' : 'Add details'}
              </Button>
            </div>
            {open === p.party && <Details clientId={clientId} row={p} onSaved={() => setOpen(null)} />}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Pay from</span>
          <select aria-label="Pay from" className="h-9 rounded-md border border-border-strong bg-transparent px-2 text-sm text-foreground" value={chosen} onChange={(e) => setAccount(e.target.value)}>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>{a.label}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Mode</span>
          <select aria-label="Payment mode" className="h-9 rounded-md border border-border-strong bg-transparent px-2 text-sm text-foreground" value={mode} onChange={(e) => setMode(e.target.value as 'NEFT' | 'RTGS' | 'IMPS')}>
            <option value="NEFT">NEFT</option>
            <option value="RTGS">RTGS (₹2,00,000 and above)</option>
            <option value="IMPS">IMPS (up to ₹5,00,000)</option>
          </select>
        </label>
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Payment date</span>
          <input aria-label="Payment date" type="date" className="h-9 rounded-md border border-border-strong bg-transparent px-2 text-sm text-foreground" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <Button loading={make.isPending} disabled={!chosen || Object.keys(picked).length === 0} onClick={build}>
          Prepare payment file
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">The columns are generic. Banks differ in layout, so check your bank&apos;s template before uploading.</p>
    </section>
  )
}
