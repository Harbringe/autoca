// Masters: the client's chart of accounts, its parties, and the rules that place rows.
//
// Ledgers are listed under Tally's primary groups, because that is how a CA reads a chart.
// Ledgers the assistant proposed wait at the top for a senior CA: accept (with the exact Tally
// name), merge into one that exists, or reject. Parties carry the GSTIN and TDS defaults.
// Rules are mostly learned from decisions in Review; they can be switched off or written by hand.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Bot, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import { journal, ledgers as ledgersQuery, parties as partiesQuery, rules as rulesQuery } from '@/api/queries/books'
import { clientDetail, useInvalidateClient, V1 } from '@/api/queries/clients'
import { GROUP_LABEL, LEDGER_GROUPS, TDS_SECTIONS, type LedgerAccount, type Party, type Rule } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox, Select, tbl } from '@/components/ui/controls'
import { Money } from '@/components/ca/Money'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, fyLabel, plural } from '@/lib/format'
import { useFy } from '@/features/shell/useFy'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export type MasterTab = 'ledgers' | 'parties' | 'rules'

export function MastersScreen({ clientId, tab }: { clientId: string; tab: MasterTab }) {
  const tabs: { tab: MasterTab; label: string }[] = [
    { tab: 'parties', label: 'Parties' },
    { tab: 'rules', label: 'Rules' },
  ]
  return (
    <div className="grid gap-4">
      <nav aria-label="Masters" className="flex w-fit gap-1 rounded-lg bg-muted p-1">
        <Link
          to="/clients/$clientId/ledgers"
          params={{ clientId }}
          className={cn('rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground', tab === 'ledgers' && 'bg-card text-foreground shadow-xs')}
        >
          Ledgers
        </Link>
        {tabs.map((t) => (
          <Link
            key={t.tab}
            to="/clients/$clientId/masters"
            params={{ clientId }}
            search={{ tab: t.tab }}
            className={cn('rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground', tab === t.tab && 'bg-card text-foreground shadow-xs')}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {tab === 'ledgers' && <Ledgers clientId={clientId} />}
      {tab === 'parties' && <Parties clientId={clientId} />}
      {tab === 'rules' && <Rules clientId={clientId} />}
    </div>
  )
}

// --- Ledgers ------------------------------------------------------------------------------------

function Ledgers({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const { fy } = useFy()
  const client = useQuery(clientDetail(clientId))
  const all = useQuery(ledgersQuery(clientId))
  const entries = useQuery(journal(clientId))
  const invalidate = useInvalidateClient(clientId)
  const [editing, setEditing] = useState<LedgerAccount | 'new' | null>(null)
  const [deciding, setDeciding] = useState<LedgerAccount | null>(null)
  const [showInactive, setShowInactive] = useState(false)
  const [selectedLedger, setSelectedLedger] = useState<string | null>(null)
  const [entrySearch, setEntrySearch] = useState('')

  if (all.isPending || entries.isPending) return <Spinner />
  if (all.error) return <ErrorState error={all.error} retry={() => void all.refetch()} />
  if (entries.error) return <ErrorState error={entries.error} retry={() => void entries.refetch()} />

  const proposed = all.data.filter((l) => l.status === 'PROPOSED')
  const active = all.data.filter((l) => l.status === 'ACTIVE' && (showInactive || l.is_active))
  const mayDecide = can('journal.approve') && !!client.data?.can_sign_off
  const manage = can('ledger.manage')
  const ledgerEntries = (entries.data ?? []).filter((entry) => entry.financial_year === fy)
  const entryStats = new Map<string, { count: number; debit: number; credit: number }>()
  for (const entry of ledgerEntries) {
    const seen = new Set<string>()
    for (const line of entry.lines) {
      const stats = entryStats.get(line.ledger_account) ?? { count: 0, debit: 0, credit: 0 }
      if (!seen.has(line.ledger_account)) {
        stats.count += 1
        seen.add(line.ledger_account)
      }
      if (line.direction === 'DR') stats.debit += line.amount_paise
      else stats.credit += line.amount_paise
      entryStats.set(line.ledger_account, stats)
    }
  }
  const selected = all.data.find((ledger) => ledger.id === selectedLedger) ?? null
  const q = entrySearch.trim().toLowerCase()
  const selectedEntries = selected
    ? ledgerEntries.filter((entry) => entry.lines.some((line) => line.ledger_account === selected.id) &&
        (!q || entry.narration.toLowerCase().includes(q) || String(entry.entry_no).includes(q)))
        .sort((a, b) => b.entry_date.localeCompare(a.entry_date) || b.entry_no - a.entry_no)
    : []

  async function remove(l: LedgerAccount) {
    try {
      await raw.delete(`${V1}/clients/${clientId}/ledgers/${l.id}/`)
      await invalidate()
      toast.success(`Ledger “${l.name}” deleted`)
    } catch (e) {
      toast.error(isApiError(e) && e.code === 'in_use' ? `“${l.name}” has posted entries, so it cannot be deleted. Edit it and untick Active instead.` : messageOf(e))
    }
  }

  return (
    <div className="grid gap-4">
      {proposed.length > 0 && (
        <Card className="grid gap-3 border-info/40 p-4">
          <div className="flex items-center gap-2 font-medium">
            <Bot className="size-4 text-info" aria-hidden /> Ledgers the assistant proposed ({proposed.length})
          </div>
          <p className="text-sm text-muted-foreground">
            {mayDecide
              ? 'Accept each with the exact name it has in Tally, merge it into a ledger that already exists, or reject it. Rows suggested into it wait until you decide.'
              : 'A senior CA who leads this client decides these.'}
          </p>
          <div className={tbl.wrap}>
            <table className={tbl.table}>
              <thead className={tbl.head}>
                <tr>
                  <th className={tbl.th}>Proposed name</th>
                  <th className={tbl.th}>Group</th>
                  <th className={tbl.th}>Why</th>
                  <th className={tbl.thNum}>Rows</th>
                  <th className={tbl.th}></th>
                </tr>
              </thead>
              <tbody>
                {proposed.map((l) => (
                  <tr key={l.id} className={tbl.row}>
                    <td className={`${tbl.td} font-medium`}>{l.name}</td>
                    <td className={tbl.td}>{GROUP_LABEL[l.group ?? ''] ?? l.group}</td>
                    <td className={`${tbl.td} max-w-md text-muted-foreground`}>{l.proposal_reason}</td>
                    <td className={tbl.tdNum}>{l.row_count}</td>
                    <td className={`${tbl.td} text-right`}>
                      {mayDecide && (
                        <Button size="sm" variant="outline" onClick={() => setDeciding(l)}>
                          Decide
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">
          {plural(active.length, 'ledger')}. Names must match the client’s Tally company exactly. Select a ledger to see its posted entries for FY {fyLabel(fy)}.
        </div>
        <div className="flex items-center gap-3">
          <Checkbox label="Show inactive" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          {manage && (
            <Button onClick={() => setEditing('new')}>
              <Plus /> New ledger
            </Button>
          )}
        </div>
      </div>

      <div className={tbl.wrap}>
        <table className={tbl.table}>
          <thead className={tbl.head}>
            <tr>
              <th className={tbl.th}>Ledger</th>
              <th className={tbl.thNum}>Rows placed</th>
              <th className={tbl.thNum}>FY {fyLabel(fy)} entries</th>
              <th className={tbl.th}></th>
            </tr>
          </thead>
          {LEDGER_GROUPS.map(([group, label]) => {
            const inGroup = active.filter((l) => l.group === group)
            if (!inGroup.length) return null
            return (
              <tbody key={group}>
                <tr className="bg-muted/40">
                  <th colSpan={4} className="px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {label}
                  </th>
                </tr>
                {inGroup.map((l) => (
                  <tr key={l.id} className={tbl.row}>
                    <td className={cn(tbl.td, 'pl-6')}>
                      <button type="button" className="font-medium text-link underline-offset-2 hover:underline" onClick={() => setSelectedLedger(l.id)}>{l.name}</button>
                      {!l.is_active && <Badge className="ml-2">Inactive</Badge>}
                    </td>
                    <td className={tbl.tdNum}>{l.row_count}</td>
                    <td className={tbl.tdNum}>{entryStats.get(l.id)?.count ?? 0}</td>
                    <td className={`${tbl.td} text-right`}>
                      {manage && group !== 'BANK' && (
                        <span className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => setEditing(l)} aria-label={`Edit ${l.name}`}>
                            Edit
                          </Button>
                          {l.row_count === 0 && (
                            <Button size="sm" variant="ghost" onClick={() => void remove(l)} aria-label={`Delete ${l.name}`}>
                              <Trash2 />
                            </Button>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            )
          })}
        </table>
      </div>

      {selected && (
        <Card className="grid gap-4 p-4" aria-label={`${selected.name} ledger details`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Ledger detail · FY {fyLabel(fy)}</div>
              <h2 className="mt-1 text-lg font-semibold">{selected.name}</h2>
              <p className="text-sm text-muted-foreground">{GROUP_LABEL[selected.group ?? ''] ?? selected.group} · {plural(selectedEntries.length, 'voucher')}</p>
            </div>
            <div className="flex items-center gap-2">
              {manage && selected.group !== 'BANK' && <Button size="sm" variant="outline" onClick={() => setEditing(selected)}>Edit ledger</Button>}
              <Button size="sm" variant="ghost" onClick={() => setSelectedLedger(null)}>Close</Button>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Card className="p-3"><div className="text-xs text-muted-foreground">Debits in FY {fyLabel(fy)}</div><Money paise={entryStats.get(selected.id)?.debit ?? 0} /></Card>
            <Card className="p-3"><div className="text-xs text-muted-foreground">Credits in FY {fyLabel(fy)}</div><Money paise={entryStats.get(selected.id)?.credit ?? 0} /></Card>
          </div>
          <Input aria-label="Search ledger entries" placeholder="Search narration or voucher number" value={entrySearch} onChange={(e) => setEntrySearch(e.target.value)} />
          {selectedEntries.length === 0 ? <p className="py-5 text-center text-sm text-muted-foreground">No posted entries for this ledger in FY {fyLabel(fy)}{q ? ' match this search.' : '.'}</p> : (
            <div className={tbl.wrap}>
              <table className={tbl.table}>
                <thead className={tbl.head}><tr><th className={tbl.th}>Date</th><th className={tbl.th}>Voucher</th><th className={tbl.th}>Narration</th><th className={tbl.thNum}>Debit</th><th className={tbl.thNum}>Credit</th></tr></thead>
                <tbody>{selectedEntries.map((entry) => {
                  const matching = entry.lines.filter((item) => item.ledger_account === selected.id)
                  const debit = matching.filter((line) => line.direction === 'DR').reduce((sum, line) => sum + line.amount_paise, 0)
                  const credit = matching.filter((line) => line.direction === 'CR').reduce((sum, line) => sum + line.amount_paise, 0)
                  return <tr key={entry.id} className={tbl.row}>
                    <td className={`${tbl.td} num whitespace-nowrap`}>{formatDate(entry.entry_date)}</td>
                    <td className={tbl.td}>{entry.voucher_type} · {entry.entry_no}</td>
                    <td className={`${tbl.td} max-w-lg truncate`} title={entry.narration}>{entry.narration}</td>
                    <td className={tbl.tdNum}>{debit > 0 && <Money paise={debit} />}</td>
                    <td className={tbl.tdNum}>{credit > 0 && <Money paise={credit} />}</td>
                  </tr>
                })}</tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {editing && <LedgerForm clientId={clientId} ledger={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {deciding && (
        <ProposalDecision clientId={clientId} proposal={deciding} existing={all.data.filter((l) => l.status === 'ACTIVE' && l.is_active)} onClose={() => setDeciding(null)} />
      )}
    </div>
  )
}

function LedgerForm({ clientId, ledger, onClose }: { clientId: string; ledger: LedgerAccount | null; onClose: () => void }) {
  const invalidate = useInvalidateClient(clientId)
  const [name, setName] = useState(ledger?.name ?? '')
  const [group, setGroup] = useState<string>(ledger?.group || 'INDIRECT_EXPENSE')
  const [active, setActive] = useState(ledger?.is_active ?? true)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    try {
      const body = { name: name.trim(), group, is_active: active }
      if (ledger) await raw.patch(`${V1}/clients/${clientId}/ledgers/${ledger.id}/`, body)
      else await raw.post(`${V1}/clients/${clientId}/ledgers/`, body)
      await invalidate()
      toast.success(ledger ? 'Ledger saved' : `Ledger “${body.name}” created`)
      onClose()
    } catch (e) {
      setError(isApiError(e) ? (e.field('name') ?? e.field('group') ?? e.message) : messageOf(e))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{ledger ? `Edit ${ledger.name}` : 'New ledger'}</DialogTitle>
          <DialogDescription>Tally creates a new ledger for any name it does not recognise, so spell it exactly as in Tally.</DialogDescription>
        </DialogHeader>
        <Field label="Name" error={error ?? undefined}>
          {(p) => <Input {...p} autoFocus value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Group (Tally primary group)">
          {(p) => (
            <Select {...p} value={group} onChange={(e) => setGroup(e.target.value)}>
              {LEDGER_GROUPS.map(([g, l]) => (
                <option key={g} value={g}>{l}</option>
              ))}
            </Select>
          )}
        </Field>
        {ledger && <Checkbox label="Active (offered when placing rows)" checked={active} onChange={(e) => setActive(e.target.checked)} />}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => void save()} disabled={name.trim().length < 2}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ProposalDecision({ clientId, proposal, existing, onClose }: { clientId: string; proposal: LedgerAccount; existing: LedgerAccount[]; onClose: () => void }) {
  const invalidate = useInvalidateClient(clientId)
  const [mode, setMode] = useState<'accept' | 'merge' | 'reject'>('accept')
  const [name, setName] = useState(proposal.name)
  const [group, setGroup] = useState<string>(proposal.group ?? 'INDIRECT_EXPENSE')
  const [into, setInto] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const base = `${V1}/clients/${clientId}/ledgers/${proposal.id}`

  async function go() {
    setBusy(true)
    setError(null)
    try {
      if (mode === 'accept') await raw.post(`${base}/accept/`, { name: name.trim(), group })
      if (mode === 'merge') await raw.post(`${base}/merge/`, { into })
      if (mode === 'reject') await raw.post(`${base}/reject/`)
      await invalidate()
      toast.success(mode === 'accept' ? 'Ledger accepted' : mode === 'merge' ? 'Merged; its rows moved across' : 'Rejected; its rows are back in Review')
      onClose()
    } catch (e) {
      setError(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Proposed ledger: {proposal.name}</DialogTitle>
          <DialogDescription>{proposal.proposal_reason || 'Proposed by the assistant.'}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          {(['accept', 'merge', 'reject'] as const).map((m) => (
            <label key={m} className={cn('flex cursor-pointer gap-2 rounded-md border p-3 text-sm', mode === m && 'border-primary bg-hover')}>
              <input type="radio" name="decision" checked={mode === m} onChange={() => setMode(m)} className="mt-0.5" />
              <span>
                <span className="font-medium">{m === 'accept' ? 'Accept' : m === 'merge' ? 'Merge into an existing ledger' : 'Reject'}</span>
                <span className="block text-muted-foreground">
                  {m === 'accept'
                    ? 'Add it to the chart, with the exact name used in Tally.'
                    : m === 'merge'
                      ? 'The client already has a ledger for this. Its rows move there.'
                      : `Not needed. ${plural(proposal.row_count, 'row')} suggested into it go back to Review.`}
                </span>
              </span>
            </label>
          ))}
        </div>
        {mode === 'accept' && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name in Tally">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
            <Field label="Group">
              {(p) => (
                <Select {...p} value={group} onChange={(e) => setGroup(e.target.value)}>
                  {LEDGER_GROUPS.map(([g, l]) => (
                    <option key={g} value={g}>{l}</option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
        )}
        {mode === 'merge' && (
          <Field label="Merge into">
            {(p) => (
              <Select {...p} value={into} onChange={(e) => setInto(e.target.value)}>
                <option value="">Choose a ledger…</option>
                {existing.map((l) => (
                  <option key={l.id} value={l.id}>{l.name} ({GROUP_LABEL[l.group ?? ''] ?? l.group})</option>
                ))}
              </Select>
            )}
          </Field>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant={mode === 'reject' ? 'destructive' : 'primary'} onClick={() => void go()} disabled={busy || (mode === 'merge' && !into) || (mode === 'accept' && name.trim().length < 2)}>
            {mode === 'accept' ? 'Accept' : mode === 'merge' ? 'Merge' : 'Reject'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Parties ------------------------------------------------------------------------------------

function Parties({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const list = useQuery(partiesQuery(clientId))
  const [editing, setEditing] = useState<Party | 'new' | null>(null)
  const [text, setText] = useState('')

  if (list.isPending) return <Spinner />
  if (list.error) return <ErrorState error={list.error} retry={() => void list.refetch()} />
  const q = text.trim().toLowerCase()
  const shown = list.data.filter((p) => !q || p.canonical_name.toLowerCase().includes(q) || (p.gstin ?? '').toLowerCase().includes(q))

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Input aria-label="Search parties" placeholder="Search by name or GSTIN" className="max-w-xs" value={text} onChange={(e) => setText(e.target.value)} />
        {can('party.manage') && (
          <Button onClick={() => setEditing('new')}>
            <Plus /> New party
          </Button>
        )}
      </div>
      {list.data.length === 0 ? (
        <EmptyState title="No parties yet">Parties are the people and businesses the client pays or is paid by. They are added as you confirm payees in Review.</EmptyState>
      ) : (
        <div className={tbl.wrap}>
          <table className={tbl.table}>
            <thead className={tbl.head}>
              <tr>
                <th className={tbl.th}>Name</th>
                <th className={tbl.th}>GSTIN</th>
                <th className={tbl.th}>TDS</th>
                <th className={tbl.th}>RCM</th>
                <th className={tbl.th}></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.id} className={tbl.row}>
                  <td className={`${tbl.td} font-medium`}>
                    {p.canonical_name}
                    {p.is_active === false && <Badge className="ml-2">Inactive</Badge>}
                  </td>
                  <td className={`${tbl.td} font-mono text-xs`}>{p.gstin || '—'}</td>
                  <td className={tbl.td}>{p.tds_section || '—'}</td>
                  <td className={tbl.td}>{p.rcm_default ? 'Yes' : '—'}</td>
                  <td className={`${tbl.td} text-right`}>
                    {can('party.manage') && (
                      <Button size="sm" variant="ghost" onClick={() => setEditing(p)} aria-label={`Edit ${p.canonical_name}`}>
                        Edit
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <PartyForm clientId={clientId} party={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function PartyForm({ clientId, party, onClose }: { clientId: string; party: Party | null; onClose: () => void }) {
  const invalidate = useInvalidateClient(clientId)
  const [name, setName] = useState(party?.canonical_name ?? '')
  const [gstin, setGstin] = useState(party?.gstin ?? '')
  const [tds, setTds] = useState<string>(party?.tds_section ?? '')
  const [rcm, setRcm] = useState(party?.rcm_default ?? false)
  const [active, setActive] = useState(party?.is_active ?? true)
  const [errors, setErrors] = useState<Record<string, string>>({})

  async function save() {
    const body = { canonical_name: name.trim(), gstin: gstin.trim().toUpperCase(), tds_section: tds, rcm_default: rcm, is_active: active }
    try {
      if (party) await raw.patch(`${V1}/clients/${clientId}/parties/${party.id}/`, body)
      else await raw.post(`${V1}/clients/${clientId}/parties/`, body)
      await invalidate()
      toast.success('Party saved')
      onClose()
    } catch (e) {
      if (isApiError(e) && Object.keys(e.fields).length) setErrors(Object.fromEntries(Object.entries(e.fields).map(([k, v]) => [k, v[0] ?? ''])))
      else setErrors({ root: messageOf(e) })
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{party ? `Edit ${party.canonical_name}` : 'New party'}</DialogTitle>
        </DialogHeader>
        <Field label="Name" error={errors.canonical_name}>
          {(p) => <Input {...p} autoFocus value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="GSTIN (optional)" hint="15 characters, for example 27ABCDE1234F1Z5." error={errors.gstin}>
          {(p) => <Input {...p} className="font-mono uppercase" maxLength={15} value={gstin} onChange={(e) => setGstin(e.target.value)} />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="TDS normally deducted">
            {(p) => (
              <Select {...p} value={tds} onChange={(e) => setTds(e.target.value)}>
                {TDS_SECTIONS.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </Select>
            )}
          </Field>
          <div className="flex items-end pb-2">
            <Checkbox label="Reverse charge by default" checked={rcm} onChange={(e) => setRcm(e.target.checked)} />
          </div>
        </div>
        {party && <Checkbox label="Active" checked={active} onChange={(e) => setActive(e.target.checked)} />}
        {errors.root && <p role="alert" className="text-sm text-destructive">{errors.root}</p>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => void save()} disabled={name.trim().length < 2}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Rules --------------------------------------------------------------------------------------

const MATCH_LABEL: Record<string, string> = {
  PARTY_EQUALS: 'Payee is',
  PARTY_CONTAINS: 'Payee contains',
  NARRATION_CONTAINS: 'Narration contains',
  CHANNEL_IS: 'Mode is',
  REGEX: 'Pattern (advanced)',
}
const SOURCE_LABEL: Record<string, string> = { SEED: 'Built in', LEARNED: 'Learned', MANUAL: 'Written by hand' }
const DIRECTION_LABEL: Record<string, string> = { ANY: 'Paid or received', DEBIT: 'Money out', CREDIT: 'Money in' }

function Rules({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const list = useQuery(rulesQuery(clientId))
  const ledgers = useQuery(ledgersQuery(clientId))
  const invalidate = useInvalidateClient(clientId)
  const [creating, setCreating] = useState(false)
  const manage = can('suggestion.edit')

  if (list.isPending) return <Spinner />
  if (list.error) return <ErrorState error={list.error} retry={() => void list.refetch()} />

  async function toggle(r: Rule) {
    try {
      await raw.patch(`${V1}/clients/${clientId}/rules/${r.id}/`, { is_active: !r.is_active })
      await invalidate()
    } catch (e) {
      toast.error(messageOf(e))
    }
  }
  async function remove(r: Rule) {
    try {
      await raw.delete(`${V1}/clients/${clientId}/rules/${r.id}/`)
      await invalidate()
      toast.success('Rule deleted')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  const sorted = [...list.data].sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0) || b.hit_count - a.hit_count)
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Rules place new rows automatically. Most are learned when you place a row in Review with “Remember this” ticked. A rule written by
          hand outranks a learned one.
        </p>
        {manage && (
          <Button onClick={() => setCreating(true)}>
            <Plus /> New rule
          </Button>
        )}
      </div>
      <div className={tbl.wrap}>
        <table className={tbl.table}>
          <thead className={tbl.head}>
            <tr>
              <th className={tbl.th}>When</th>
              <th className={tbl.th}>Direction</th>
              <th className={tbl.th}>Place in</th>
              <th className={tbl.th}>Source</th>
              <th className={tbl.thNum}>Used</th>
              <th className={tbl.th}>Last used</th>
              <th className={tbl.th}>Active</th>
              <th className={tbl.th}></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.id} className={cn(tbl.row, !r.is_active && 'text-muted-foreground')}>
                <td className={tbl.td}>
                  <span className="text-muted-foreground">{MATCH_LABEL[r.match_type ?? ''] ?? r.match_type} </span>
                  <span className="font-medium">{r.pattern}</span>
                </td>
                <td className={tbl.td}>{DIRECTION_LABEL[r.direction ?? 'ANY']}</td>
                <td className={tbl.td}>{r.ledger_name}</td>
                <td className={tbl.td}>{SOURCE_LABEL[r.source] ?? r.source}</td>
                <td className={tbl.tdNum}>{r.hit_count}</td>
                <td className={`${tbl.td} num`}>{r.last_hit_at ? formatDate(r.last_hit_at.slice(0, 10)) : '—'}</td>
                <td className={tbl.td}>
                  <Checkbox aria-label={`Active: ${MATCH_LABEL[r.match_type ?? ''] ?? r.match_type} ${r.pattern}, ${DIRECTION_LABEL[r.direction ?? 'ANY']}, to ${r.ledger_name}`} checked={!!r.is_active} disabled={!manage} onChange={() => void toggle(r)} />
                </td>
                <td className={`${tbl.td} text-right`}>
                  {manage && r.source !== 'SEED' && (
                    <Button size="sm" variant="ghost" onClick={() => void remove(r)} aria-label={`Delete rule: ${MATCH_LABEL[r.match_type ?? ''] ?? r.match_type} ${r.pattern} to ${r.ledger_name}`}>
                      <Trash2 />
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating && <RuleForm clientId={clientId} ledgers={(ledgers.data ?? []).filter((l) => l.status === 'ACTIVE' && l.is_active)} onClose={() => setCreating(false)} />}
    </div>
  )
}

function RuleForm({ clientId, ledgers, onClose }: { clientId: string; ledgers: LedgerAccount[]; onClose: () => void }) {
  const invalidate = useInvalidateClient(clientId)
  const [matchType, setMatchType] = useState('NARRATION_CONTAINS')
  const [pattern, setPattern] = useState('')
  const [direction, setDirection] = useState('ANY')
  const [ledger, setLedger] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function save() {
    try {
      await raw.post(`${V1}/clients/${clientId}/rules/`, { match_type: matchType, pattern: pattern.trim(), direction, ledger })
      await invalidate()
      toast.success('Rule created; it applies to rows uploaded from now on')
      onClose()
    } catch (e) {
      setError(isApiError(e) ? (e.field('pattern') ?? e.message) : messageOf(e))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>New rule</DialogTitle>
          <DialogDescription>Rows that match are placed in the ledger automatically, for you to check before posting.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="When">
            {(p) => (
              <Select {...p} value={matchType} onChange={(e) => setMatchType(e.target.value)}>
                {Object.entries(MATCH_LABEL).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Text" error={error ?? undefined}>
            {(p) => <Input {...p} autoFocus value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="e.g. ELECTRICITY" />}
          </Field>
        </div>
        <Field label="Direction">
          {(p) => (
            <Select {...p} value={direction} onChange={(e) => setDirection(e.target.value)}>
              {Object.entries(DIRECTION_LABEL).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Place in ledger">
          {(p) => (
            <Select {...p} value={ledger} onChange={(e) => setLedger(e.target.value)}>
              <option value="">Choose a ledger…</option>
              {ledgers.map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </Select>
          )}
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => void save()} disabled={!pattern.trim() || !ledger}>Create rule</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
