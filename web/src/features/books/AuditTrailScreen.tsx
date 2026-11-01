// The audit trail: every change to the client's vouchers and to its ledgers, parties and rules, newest first, with who made it and
// what it was before and after. Filter by kind, date or text; open a change to see only the fields that moved.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { auditTrail, type AuditRow, type ChangeKind } from '@/api/queries/auditTrail'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDateTime } from '@/lib/format'

const PAGE = 50
const KIND_LABEL: Record<string, string> = { ENTRY: 'Voucher', LEDGER: 'Ledger', PARTY: 'Party', RULE: 'Rule', SETTING: 'Setting' }

const show = (value: unknown) => (value === undefined || value === null || value === '' ? '(none)' : typeof value === 'object' ? JSON.stringify(value) : String(value))

/** The fields whose value differs, each with what it was and what it became. */
function changedFields(row: AuditRow): { field: string; before: unknown; after: unknown }[] {
  const names = [...new Set([...Object.keys(row.before ?? {}), ...Object.keys(row.after ?? {})])]
  return names.filter((n) => JSON.stringify(row.before?.[n]) !== JSON.stringify(row.after?.[n])).map((field) => ({ field, before: row.before?.[field], after: row.after?.[field] }))
}

export function AuditTrailScreen({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<'' | ChangeKind>('')
  const [q, setQ] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const list = useQuery(auditTrail(clientId, { kind, q, from, to, offset, limit: PAGE }))

  // Any change to a filter starts again from the first page.
  function change<T>(set: (v: T) => void, value: T) {
    set(value)
    setOffset(0)
  }

  return (
    <div className="grid gap-3">
      <Card className="flex flex-wrap items-end gap-3 p-3">
        <Select aria-label="Kind of change" className="w-44" value={kind} onChange={(e) => change(setKind, e.target.value as '' | ChangeKind)}>
          <option value="">Everything</option>
          <option value="ENTRY">Vouchers</option>
          <option value="LEDGER">Ledgers</option>
          <option value="PARTY">Parties</option>
          <option value="RULE">Rules</option>
          <option value="SETTING">Settings</option>
        </Select>
        <Input aria-label="Search the changes" placeholder="Search…" className="w-56" value={q} onChange={(e) => change(setQ, e.target.value)} />
        <Input aria-label="From" type="date" className="w-40" value={from} onChange={(e) => change(setFrom, e.target.value)} />
        <Input aria-label="To" type="date" className="w-40" value={to} onChange={(e) => change(setTo, e.target.value)} />
      </Card>

      {list.isPending ? (
        <Spinner />
      ) : list.error ? (
        <ErrorState error={list.error} retry={() => void list.refetch()} />
      ) : list.data.results.length === 0 ? (
        <EmptyState title="Nothing has been changed">Vouchers made or changed, and changes to ledgers, parties, rules and settings are listed here as they happen.</EmptyState>
      ) : (
        <>
          <ul aria-label="Changes" className="divide-y divide-border-strong overflow-hidden rounded-xl border border-border-strong bg-card text-sm">
            {list.data.results.map((r) => {
              const fields = changedFields(r)
              return (
                <li key={r.id} className="grid gap-1 px-4 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p>
                      <span className="text-muted-foreground">{KIND_LABEL[r.kind] ?? r.kind} · </span>
                      <span className="font-medium">{r.action_display}</span> · {r.label}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {r.actor_name || 'The assistant'} · {formatDateTime(r.at)}
                    </p>
                  </div>
                  {r.note && <p className="text-muted-foreground">{r.note}</p>}
                  {fields.length > 0 && (
                    <div>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-expanded={open === r.id}
                        aria-label={`Show what changed: ${r.label}`}
                        onClick={() => setOpen(open === r.id ? null : r.id)}
                      >
                        {open === r.id ? 'Hide' : 'What changed'}
                      </Button>
                      {open === r.id && (
                        <dl data-testid={`diff-${r.id}`} className="mt-1 grid gap-1 rounded-lg bg-hover p-2">
                          {fields.map((f) => (
                            <div key={f.field} className="flex flex-wrap gap-x-2">
                              <dt className="font-medium">{f.field}</dt>
                              <dd className="text-muted-foreground">
                                {show(f.before)} → {show(f.after)}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      )}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {offset + 1}–{Math.min(offset + PAGE, list.data.count)} of {list.data.count}
            </span>
            <span className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                Previous
              </Button>
              <Button variant="outline" size="sm" disabled={offset + PAGE >= list.data.count} onClick={() => setOffset(offset + PAGE)}>
                Next
              </Button>
            </span>
          </div>
        </>
      )}
    </div>
  )
}
