// Creating an account (a ledger) where it is needed, without leaving the form.
//
// Says in words what each group is for and where the account will show in the statements, and warns when a similar account
// already exists, because a second "Courier" next to "Courier Charges" splits a year of entries.

import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import { GROUP_LABEL, type LedgerAccount } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'

interface GroupInfo {
  code: string
  /** What it is, in a line. */
  help: string
  /** Where it appears. */
  shows: string
}

/** Grouped by what the account is, in the order a chart of accounts is read. Bank and Suspense are never made by hand. */
const GROUPS: { title: string; groups: GroupInfo[] }[] = [
  {
    title: 'Expenses',
    groups: [
      { code: 'INDIRECT_EXPENSE', help: 'Running costs: rent, salaries, fuel, repairs, professional fees.', shows: 'Profit and Loss, under expenses' },
      { code: 'DIRECT_EXPENSE', help: 'Costs of making or buying what you sell: freight, wages on production, packing.', shows: 'Profit and Loss, under cost of goods' },
    ],
  },
  {
    title: 'Income',
    groups: [
      { code: 'INDIRECT_INCOME', help: 'Income that is not your main sales: interest, commission, discount received.', shows: 'Profit and Loss, under other income' },
      { code: 'DIRECT_INCOME', help: 'Income from the work itself, such as service fees or job work.', shows: 'Profit and Loss, under income' },
    ],
  },
  {
    title: 'What the business owns and owes',
    groups: [
      { code: 'CREDITOR', help: 'A supplier or anyone you owe money to for goods or services.', shows: 'Balance Sheet, under payables' },
      { code: 'DEBTOR', help: 'A customer or anyone who owes you money for goods or services.', shows: 'Balance Sheet, under receivables' },
      { code: 'LOAN', help: 'Money borrowed that has to be repaid: a bank loan, a loan from a friend.', shows: 'Balance Sheet, under borrowings' },
      { code: 'DUTIES_AND_TAXES', help: 'GST, TDS and other taxes collected or payable.', shows: 'Balance Sheet, under taxes and duties' },
      { code: 'INVESTMENT', help: 'Shares, mutual funds, fixed deposits kept as investments.', shows: 'Balance Sheet, under investments' },
      { code: 'CASH', help: 'Cash in hand.', shows: 'Balance Sheet, under cash' },
      { code: 'CAPITAL', help: "The owner's or partners' capital, drawings and reserves.", shows: "Balance Sheet, under owners' funds" },
    ],
  },
]

const norm = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, '')

export function NewAccountDialog({
  clientId,
  ledgers,
  initialName = '',
  initialGroup = 'INDIRECT_EXPENSE',
  onCreated,
  onClose,
}: {
  clientId: string
  /** The accounts the client already has, to warn about a name that is nearly the same. */
  ledgers: LedgerAccount[]
  initialName?: string
  initialGroup?: string
  onCreated: (ledger: LedgerAccount) => void
  onClose: () => void
}) {
  const invalidate = useInvalidateClient(clientId)
  const [name, setName] = useState(initialName)
  const [group, setGroup] = useState(GROUPS.some((s) => s.groups.some((g) => g.code === initialGroup)) ? initialGroup : 'INDIRECT_EXPENSE')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const info = GROUPS.flatMap((s) => s.groups).find((g) => g.code === group)
  const similar = useMemo(() => {
    const key = norm(name)
    if (key.length < 3) return null
    return ledgers.find((l) => norm(l.name) === key || (key.length >= 5 && (norm(l.name).includes(key) || key.includes(norm(l.name))) && norm(l.name).length >= 5)) ?? null
  }, [ledgers, name])
  const exact = similar && norm(similar.name) === norm(name)

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const made = await raw.post<LedgerAccount>(`${V1}/clients/${clientId}/ledgers/`, { name: name.trim(), group })
      await invalidate()
      toast.success(`Account “${made.name}” created under ${GROUP_LABEL[made.group ?? ''] ?? made.group}`)
      onCreated(made)
    } catch (e) {
      setError(isApiError(e) ? (e.field('name') ?? e.field('group') ?? e.message) : messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent aria-describedby={undefined} className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New account</DialogTitle>
          <DialogDescription>
            Spell it as it is in the client’s Tally company: Tally makes a new account for any name it does not recognise.
          </DialogDescription>
        </DialogHeader>

        <Field label="Account name" error={error ?? undefined}>
          {(props) => <Input {...props} autoFocus value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        {similar && (
          <p role="status" className="rounded-md border border-accent-edge bg-accent p-2 text-sm">
            {exact ? 'There is already an account called' : 'A similar account already exists:'} <strong>{similar.name}</strong>
            {` (${GROUP_LABEL[similar.group ?? ''] ?? similar.group})`}. Use that one unless this is truly different.
          </p>
        )}

        <Field label="What kind of account is it?">
          {(props) => (
            <Select {...props} value={group} onChange={(e) => setGroup(e.target.value)}>
              {GROUPS.map((section) => (
                <optgroup key={section.title} label={section.title}>
                  {section.groups.map((g) => (
                    <option key={g.code} value={g.code}>{GROUP_LABEL[g.code]}</option>
                  ))}
                </optgroup>
              ))}
            </Select>
          )}
        </Field>
        {info && (
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            <div>{info.help}</div>
            <div className="mt-1 text-muted-foreground">Shows in: {info.shows}.</div>
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => void create()} disabled={busy || name.trim().length < 2 || !!exact}>
            Create and use
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
