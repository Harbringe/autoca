// The review screen. Sorted by confidence, because that ordering is what
// turns an hour of checking every row into minutes of checking the ones that
// need it. High-confidence rows can be approved in one click by someone who
// may approve; everything else is placed one at a time -- and each placement
// teaches a rule that usually places several siblings.

import { useMemo, useState, type FormEvent } from 'react'
import { allPages, api, V1, waitForJob } from '../../api/client'
import type { BankAccount, Classification, Client, Job, LedgerAccount, PlacementResult, ReviewBand, ReviewSummary, Vendor } from '../../api/types'
import { LEDGER_GROUPS, TDS_SECTIONS } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, BandBadge, Button, Confidence, Empty, ErrorNote, Field, formatDate, Modal, Money, Note, Spinner, useAsync } from '../../components/ui'
import { RecategorizeButton } from './Recategorize'

type Stage = 'all' | 'unresolved' | 'pending_approval'

export default function ReviewQueue({ client }: { client: Client }) {
  const { can } = useSession()
  const [band, setBand] = useState<ReviewBand | ''>('')
  const [stage, setStage] = useState<Stage>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [placing, setPlacing] = useState<Classification | null>(null)
  const [flash, setFlash] = useState<{ tone: 'good' | 'warn' | 'bad' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const summary = useAsync(() => api.get<ReviewSummary>(`${V1}/clients/${client.id}/review-queue/summary/`), [client.id])
  const queue = useAsync(() => {
    const params = new URLSearchParams()
    if (band) params.set('band', band)
    if (stage !== 'all') params.set('stage', stage)
    const qs = params.toString()
    return allPages<Classification>(`${V1}/clients/${client.id}/review-queue/${qs ? `?${qs}` : ''}`)
  }, [client.id, band, stage])
  const ledgers = useAsync(() => allPages<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/`), [client.id])
  const vendors = useAsync(() => allPages<Vendor>(`${V1}/clients/${client.id}/vendors/`), [client.id])
  const accounts = useAsync(() => allPages<BankAccount>(`${V1}/clients/${client.id}/bank-accounts/`), [client.id])

  const reload = () => {
    summary.reload()
    queue.reload()
    setSelected(new Set())
  }

  const approvable = useMemo(() => (queue.data ?? []).filter((c) => c.ledger && !c.is_posted), [queue.data])

  async function approve(body: { classifications?: string[]; band?: ReviewBand }, label: string) {
    setBusy(label)
    setError(null)
    setFlash(null)
    try {
      const entries = await api.post<unknown[]>(`${V1}/clients/${client.id}/approvals/`, body)
      setFlash({ tone: 'good', text: `Posted ${entries.length} journal entr${entries.length === 1 ? 'y' : 'ies'}.` })
      reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  async function askModel() {
    setBusy('model')
    setError(null)
    setFlash(null)
    try {
      const started = await api.post<Job>(`${V1}/clients/${client.id}/review-queue/suggest/`)
      const job = await waitForJob(started)
      if (job.status === 'FAILED') throw new Error(job.error)
      const r = job.result as Record<string, number | string>
      if (r.error) setFlash({ tone: 'warn', text: `The model could not be reached: ${String(r.error)}. Rows stay in the queue for a person.` })
      else if (Number(r.considered) === 0) setFlash({ tone: 'info', text: 'Nothing unresolved to ask about — or no model is configured (LLM_BACKEND).' })
      else setFlash({ tone: 'info', text: `The model suggested ledgers for ${String(r.suggested)} of ${String(r.considered)} rows and declined ${String(r.declined)}.${Number(r.proposed) > 0 ? ` It proposed ${String(r.proposed)} new ledger${Number(r.proposed) === 1 ? '' : 's'}, waiting for a CA under Chart of accounts.` : ''} Every suggestion still needs a person.` })
      reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const s = summary.data

  return (
    <>
      {s && (
        <div className="grid-cards">
          <SummaryCard label="High confidence" value={s.high} hint="bulk-approvable" onClick={() => setBand(band === 'HIGH' ? '' : 'HIGH')} selected={band === 'HIGH'} />
          <SummaryCard label="Review advised" value={s.advised} onClick={() => setBand(band === 'ADVISED' ? '' : 'ADVISED')} selected={band === 'ADVISED'} />
          <SummaryCard label="Needs judgement" value={s.judgement} onClick={() => setBand(band === 'JUDGEMENT' ? '' : 'JUDGEMENT')} selected={band === 'JUDGEMENT'} />
          <SummaryCard label="Unresolved" value={s.unresolved} hint="no ledger yet" onClick={() => setStage(stage === 'unresolved' ? 'all' : 'unresolved')} selected={stage === 'unresolved'} />
          <SummaryCard label="Awaiting approval" value={s.pending_approval} hint="placed, not posted" onClick={() => setStage(stage === 'pending_approval' ? 'all' : 'pending_approval')} selected={stage === 'pending_approval'} />
        </div>
      )}

      <ErrorNote error={error ?? queue.error ?? summary.error} />
      {flash && <Note tone={flash.tone}>{flash.text}</Note>}

      <div className="panel">
        <div className="filter-bar">
          <span className="sub">{queue.data?.length ?? 0} rows</span>
          {(band || stage !== 'all') && (
            <Button className="btn-sm" kind="ghost" onClick={() => (setBand(''), setStage('all'))}>
              Clear filters
            </Button>
          )}
          <span className="row" />
          {can('transaction.classify') && (
            <Button className="btn-sm" onClick={() => void askModel()} busy={busy === 'model'} disabled={!!busy}>
              Ask the model about unresolved rows
            </Button>
          )}
          {can('transaction.classify') && (
            <RecategorizeButton
              client={client}
              label="Re-categorize all with AI"
              disabled={!!busy}
              onBusy={(b) => setBusy(b ? 'recat' : null)}
              onResult={(f) => {
                setFlash(f)
                reload()
              }}
            />
          )}
          {can('journal.approve') && (
            <>
              <Button className="btn-sm" kind="primary" onClick={() => void approve({ band: 'HIGH' }, 'high')} busy={busy === 'high'} disabled={!!busy || !(s?.high && approvable.some((c) => c.review_band === 'HIGH'))}>
                Approve all high-confidence
              </Button>
              <Button className="btn-sm" kind="primary" onClick={() => void approve({ classifications: [...selected] }, 'sel')} busy={busy === 'sel'} disabled={!!busy || selected.size === 0}>
                Approve {selected.size || ''} selected
              </Button>
            </>
          )}
        </div>

        {queue.loading ? (
          <Spinner />
        ) : !queue.data?.length ? (
          <Empty title="Nothing waiting">Every row here has been posted to the ledger, or there are no statements yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  {can('journal.approve') && <th></th>}
                  <th>Date</th>
                  <th>Transaction</th>
                  <th className="num">Amount</th>
                  <th>Suggested treatment</th>
                  <th>Confidence</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {queue.data.map((c) => (
                  <tr key={c.id}>
                    {can('journal.approve') && (
                      <td>
                        <input type="checkbox" disabled={!c.ledger || c.ledger_status === 'PROPOSED'} checked={selected.has(c.id)} onChange={() => toggle(c.id)} aria-label="Select for approval" />
                      </td>
                    )}
                    <td>{formatDate(c.transaction.value_date)}</td>
                    <td className="narr">
                      <div className="mono">{c.transaction.narration}</div>
                      <div className="pill-row tiny">
                        {c.channel && c.channel !== 'UNKNOWN' && <Badge>{c.channel}</Badge>}
                        {c.counterparty && <span>{c.counterparty}</span>}
                        {c.is_self_transfer && <Badge tone="info">own account</Badge>}
                      </div>
                    </td>
                    <td className={`num ${c.transaction.is_debit ? 'dr' : 'cr'}`}>
                      <Money value={c.transaction.amount_display} />
                      <div className="tiny">{c.transaction.is_debit ? 'Dr · paid' : 'Cr · received'}</div>
                    </td>
                    <td>
                      {c.ledger_name ? (
                        <>
                          <strong>{c.ledger_name}</strong>
                          {c.ledger_status === 'PROPOSED' && (
                            <div>
                              <Badge tone="warn">New ledger · awaiting CA</Badge>
                            </div>
                          )}
                          {c.vendor_name && <div className="tiny">Party: {c.vendor_name}</div>}
                          <div className="pill-row tiny">
                            <span>{c.method_display}</span>
                            {c.rcm && <Badge tone="warn">RCM</Badge>}
                            {c.tds_section && <Badge tone="info">TDS {c.tds_section}</Badge>}
                          </div>
                        </>
                      ) : (
                        <span className="tiny">No suggestion</span>
                      )}
                      {c.rationale && <div className="rationale">“{c.rationale}”</div>}
                    </td>
                    <td>
                      <BandBadge band={c.review_band} />
                      <div>
                        <Confidence value={c.confidence} />
                      </div>
                    </td>
                    <td className="num">
                      {can('transaction.classify') && (
                        <Button className="btn-sm" onClick={() => setPlacing(c)}>
                          {c.ledger ? 'Change' : 'Place'}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {placing && (
        <PlaceRow
          client={client}
          row={placing}
          ledgers={(ledgers.data ?? []).filter((l) => l.name !== accounts.data?.find((a) => a.id === placing.transaction.bank_account)?.ledger_name)}
          vendors={vendors.data ?? []}
          onClose={() => setPlacing(null)}
          onDone={(result) => {
            setPlacing(null)
            setFlash({
              tone: 'good',
              text: result.also_placed > 0 ? `Placed. The rule learned from this also placed ${result.also_placed} other row${result.also_placed === 1 ? '' : 's'}.` : result.rule_learned ? 'Placed, and a rule was learned for this payee.' : 'Placed.',
            })
            ledgers.reload()
            vendors.reload()
            reload()
          }}
        />
      )}
    </>
  )
}

function SummaryCard({ label, value, hint, onClick, selected }: { label: string; value: number; hint?: string; onClick: () => void; selected: boolean }) {
  return (
    <div className={`card selectable ${selected ? 'selected' : ''}`} onClick={onClick} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onClick()}>
      <div className="k">{label}</div>
      <div className="v">{value}</div>
      {hint && <div className="tiny">{hint}</div>}
    </div>
  )
}

function PlaceRow({
  client,
  row,
  ledgers,
  vendors,
  onClose,
  onDone,
}: {
  client: Client
  row: Classification
  ledgers: LedgerAccount[]
  vendors: Vendor[]
  onClose: () => void
  onDone: (result: PlacementResult) => void
}) {
  const [ledger, setLedger] = useState(row.ledger ?? '')
  const [newLedger, setNewLedger] = useState('')
  const [newGroup, setNewGroup] = useState(row.transaction.is_debit ? 'INDIRECT_EXPENSE' : 'INDIRECT_INCOME')
  const [vendor, setVendor] = useState(row.vendor ?? '')
  const [newVendor, setNewVendor] = useState('')
  const [rcm, setRcm] = useState(row.rcm)
  const [tds, setTds] = useState(row.tds_section)
  const [learn, setLearn] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      let ledgerId = ledger
      if (ledger === '__new__') {
        const created = await api.post<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/`, { name: newLedger.trim(), group: newGroup })
        ledgerId = created.id
      }
      let vendorId: string | null = vendor || null
      if (vendor === '__new__') {
        const created = await api.post<Vendor>(`${V1}/clients/${client.id}/vendors/`, { canonical_name: newVendor.trim(), rcm_default: rcm, tds_section: tds })
        vendorId = created.id
      }
      const result = await api.post<PlacementResult>(`${V1}/classifications/${row.id}/review/`, {
        ledger: ledgerId,
        vendor: vendorId,
        rcm,
        tds_section: tds,
        learn,
      })
      onDone(result)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const activeLedgers = ledgers.filter((l) => l.is_active && l.status === 'ACTIVE')
  const grouped = LEDGER_GROUPS.map((g) => ({ ...g, items: activeLedgers.filter((l) => l.group === g.value) })).filter((g) => g.items.length)

  return (
    <Modal title="Place this transaction" onClose={onClose}>
      <div className="kv">
        <dt>Date</dt>
        <dd>{formatDate(row.transaction.value_date)}</dd>
        <dt>Amount</dt>
        <dd className={row.transaction.is_debit ? 'dr' : 'cr'}>
          <Money value={row.transaction.amount_display} /> {row.transaction.is_debit ? '(paid out)' : '(received)'}
        </dd>
        <dt>Narration</dt>
        <dd className="mono">{row.transaction.narration}</dd>
        {row.counterparty && (
          <>
            <dt>Counterparty</dt>
            <dd>{row.counterparty}</dd>
          </>
        )}
        {row.rationale && (
          <>
            <dt>Model said</dt>
            <dd className="rationale">“{row.rationale}”</dd>
          </>
        )}
      </div>
      <hr className="sep" />
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Ledger head" hint="Must match the ledger name in the client's Tally company exactly.">
          <select required value={ledger} onChange={(e) => setLedger(e.target.value)} autoFocus>
            <option value="">— choose —</option>
            {grouped.map((g) => (
              <optgroup key={g.value} label={g.label}>
                {g.items.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </optgroup>
            ))}
            <option value="__new__">+ New ledger…</option>
          </select>
        </Field>
        {ledger === '__new__' && (
          <div className="inline-form">
            <Field label="New ledger name">
              <input type="text" required value={newLedger} onChange={(e) => setNewLedger(e.target.value)} />
            </Field>
            <Field label="Group">
              <select value={newGroup} onChange={(e) => setNewGroup(e.target.value)}>
                {LEDGER_GROUPS.map((g) => (
                  <option key={g.value} value={g.value}>
                    {g.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}
        <Field label="Party (vendor)" hint="Who it was with, where there is an identifiable one. Optional.">
          <select value={vendor} onChange={(e) => setVendor(e.target.value)}>
            <option value="">— none —</option>
            {vendors
              .filter((v) => v.is_active)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.canonical_name}
                </option>
              ))}
            <option value="__new__">+ New party…</option>
          </select>
        </Field>
        {vendor === '__new__' && (
          <Field label="New party name">
            <input type="text" required value={newVendor || row.counterparty} onChange={(e) => setNewVendor(e.target.value)} />
          </Field>
        )}
        <div className="inline-form">
          <Field label="TDS section">
            <select value={tds} onChange={(e) => setTds(e.target.value)}>
              {TDS_SECTIONS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <label className="check">
            <input type="checkbox" checked={rcm} onChange={(e) => setRcm(e.target.checked)} />
            Reverse charge applies (client pays the GST)
          </label>
        </div>
        <label className="check">
          <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />
          Learn a rule for this payee, so it is placed automatically from now on
        </label>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Place
          </Button>
        </div>
      </form>
    </Modal>
  )
}
