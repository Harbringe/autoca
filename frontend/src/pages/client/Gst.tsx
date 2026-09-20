// GST reconciliation: purchase register against GSTR-2B, one GSTIN and one
// return month at a time.
//
// The order of the screen is the order of the work: pick the GSTIN and month,
// load the two files, match, then go through what did not match. Nothing is
// final until a senior signs it off; until then every decision can be changed
// by making a new one.

import { useEffect, useState, type FormEvent } from 'react'
import { api, V1 } from '../../api/client'
import type { Client, GstGroup, GstMatchRow, GstRegistration, GstRun, GstRunSummary } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, Button, Empty, ErrorNote, Field, formatDate, Note, Spinner, useAsync } from '../../components/ui'

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })
const formatPaise = (paise: number) => inr.format(paise / 100)

const monthLabel = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })

const DECISIONS: { kind: string; label: string; for: string[] }[] = [
  { kind: 'claim_itc', label: 'Claim credit', for: ['amount_mismatch', 'possible_match', 'tax_head_mismatch'] },
  { kind: 'disallow_itc', label: 'Disallow', for: ['matched', 'amount_mismatch', 'possible_match', 'tax_head_mismatch', 'import', 'isd_credit'] },
  { kind: 'defer', label: 'Defer', for: ['amount_mismatch', 'possible_match', 'tax_head_mismatch', 'wrong_period', 'missing_in_2b', 'missing_in_books'] },
]

export default function Gst({ client }: { client: Client }) {
  const { can } = useSession()
  const base = `${V1}/clients/${client.id}/gst`
  const regs = useAsync(() => api.get<GstRegistration[]>(`${base}/registrations/`), [client.id])
  const runs = useAsync(() => api.get<GstRunSummary[]>(`${base}/runs/`), [client.id])
  const [selected, setSelected] = useState<string | null>(null)

  const reload = () => {
    regs.reload()
    runs.reload()
  }

  return (
    <>
      <Registrations base={base} regs={regs.data} loading={regs.loading} error={regs.error} onChanged={reload} canEdit={can('gst.prepare')} />
      {regs.data && regs.data.length > 0 && (
        <Runs base={base} regs={regs.data} runs={runs.data ?? []} selected={selected} onSelect={setSelected} onChanged={runs.reload} canEdit={can('gst.prepare')} />
      )}
      {selected && <RunView key={selected} base={base} runId={selected} onChanged={runs.reload} />}
    </>
  )
}

function Registrations({ base, regs, loading, error, onChanged, canEdit }: { base: string; regs: GstRegistration[] | null; loading: boolean; error: unknown; onChanged: () => void; canEdit: boolean }) {
  const [gstin, setGstin] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function add(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await api.post(`${base}/registrations/`, { gstin: gstin.trim().toUpperCase() })
      setGstin('')
      onChanged()
    } catch (x) {
      setErr(x)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>GST registrations</h2>
      </div>
      <div className="panel-body">
        <ErrorNote error={error} />
        {loading ? (
          <Spinner />
        ) : !regs?.length ? (
          <Empty title="No GSTIN yet">Add each GSTIN this client holds. A client with registrations in several states is reconciled and reported once per GSTIN.</Empty>
        ) : (
          <ul className="plain">
            {regs.map((r) => (
              <li key={r.id}>
                <span className="mono">{r.gstin}</span> <Badge>State {r.state_code}</Badge>
              </li>
            ))}
          </ul>
        )}
        {canEdit && (
          <form onSubmit={add} className="inline-form">
            <Field label="Add a GSTIN">
              <input value={gstin} onChange={(e) => setGstin(e.target.value)} maxLength={15} placeholder="27AAAPL1234C1Z5" className="mono" />
            </Field>
            <Button kind="primary" type="submit" busy={busy} disabled={gstin.trim().length !== 15}>
              Add
            </Button>
            <ErrorNote error={err} />
          </form>
        )}
      </div>
    </div>
  )
}

function Runs({ base, regs, runs, selected, onSelect, onChanged, canEdit }: { base: string; regs: GstRegistration[]; runs: GstRunSummary[]; selected: string | null; onSelect: (id: string) => void; onChanged: () => void; canEdit: boolean }) {
  const [registration, setRegistration] = useState(regs[0].id)
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7))
  const [err, setErr] = useState<unknown>(null)

  async function open(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    try {
      const run = await api.post<GstRun>(`${base}/runs/`, { registration, period })
      onChanged()
      onSelect(run.id)
    } catch (x) {
      setErr(x)
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Reconciliations</h2>
      </div>
      <div className="panel-body">
        {canEdit && (
          <form onSubmit={open} className="inline-form">
            <Field label="GSTIN">
              <select value={registration} onChange={(e) => setRegistration(e.target.value)}>
                {regs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.gstin}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Return month">
              <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />
            </Field>
            <Button kind="primary" type="submit">
              Open
            </Button>
          </form>
        )}
        <ErrorNote error={err} />
        {runs.length > 0 && (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>GSTIN</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className={r.id === selected ? 'selected' : ''}>
                    <td>{monthLabel(r.period_start)}</td>
                    <td className="mono">{r.gstin}</td>
                    <td>{r.status === 'signed_off' ? <Badge tone="good">Signed off</Badge> : <Badge tone="warn">Draft</Badge>}</td>
                    <td>
                      <Button kind="ghost" className="btn-sm" onClick={() => onSelect(r.id)}>
                        Open
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function RunView({ base, runId, onChanged }: { base: string; runId: string; onChanged: () => void }) {
  const { can } = useSession()
  const [run, setRun] = useState<GstRun | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const url = `${base}/runs/${runId}`

  useEffect(() => {
    api.get<GstRun>(`${url}/`).then(setRun, setError)
  }, [url])

  async function act<T>(work: () => Promise<T>, apply?: (result: T) => void) {
    setBusy(true)
    setError(null)
    try {
      const result = await work()
      apply?.(result)
      onChanged()
    } catch (x) {
      setError(x)
    } finally {
      setBusy(false)
    }
  }

  async function upload(kind: 'register' | 'portal', file: File) {
    const form = new FormData()
    form.append('file', file)
    await act(() => api.post<{ run: GstRun }>(`${url}/${kind}/`, form), (r) => setRun(r.run))
  }

  if (!run) return error ? <ErrorNote error={error} /> : <Spinner />
  const locked = run.status === 'signed_off'
  const canPrepare = can('gst.prepare') && !locked
  const s = run.summary
  const ready = run.has_register && run.has_portal

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>
          {monthLabel(run.period_start)} · <span className="mono">{run.registration.gstin}</span>
        </h2>
        {locked ? <Badge tone="good">Signed off {formatDate(run.signed_off_at)}</Badge> : <Badge tone="warn">Draft — not final</Badge>}
      </div>
      <div className="panel-body">
        <ErrorNote error={error} />

        {canPrepare && (
          <div className="inline-form">
            <FileButton label={run.has_register ? 'Replace purchase register' : 'Upload purchase register'} accept=".xlsx,.csv" onFile={(f) => upload('register', f)} busy={busy} />
            <FileButton label={run.has_portal ? 'Replace GSTR-2B' : 'Upload GSTR-2B'} accept=".json,.xlsx,.csv" onFile={(f) => upload('portal', f)} busy={busy} />
            <Button kind="primary" busy={busy} disabled={!ready} onClick={() => act(() => api.post<GstRun>(`${url}/reconcile/`), setRun)}>
              Match
            </Button>
          </div>
        )}
        {!ready && !locked && <Note>Load the purchase register and the GSTR-2B (JSON as downloaded from the portal, or Excel), then match.</Note>}

        {run.groups.length > 0 && (
          <>
            <div className="tiles">
              <Tile label="Eligible ITC" value={formatPaise(s.eligible_paise)} tone="good" />
              <Tile label="Blocked credit" value={formatPaise(s.blocked_paise)} />
              <Tile label="Not claimable yet" value={formatPaise(s.ineligible_paise)} tone="warn" />
              <Tile label="Reverse-charge tax to pay" value={formatPaise(s.rcm_liability_paise)} />
              <Tile label="In 2B, not booked" value={formatPaise(s.unclaimed_in_2b_paise)} />
            </div>

            {run.actions.length > 0 && (
              <div className="subpanel">
                <h3>Action list</h3>
                <ol>
                  {run.actions.map((a) => (
                    <li key={a.match}>{a.text}</li>
                  ))}
                </ol>
              </div>
            )}

            {run.groups.map((g) => (
              <Group key={g.kind} group={g} canDecide={canPrepare} onDecide={(match, kind, note) => act(() => api.post<GstRun>(`${url}/decisions/`, { match, kind, note }), setRun)} />
            ))}

            <Table4 lines={run.gstr3b} />

            <div className="inline-form">
              <a className="btn btn-default" href={`${url}/export/`}>
                Download working paper (Excel)
              </a>
              {can('gst.sign_off') && !locked && (
                <Button kind="primary" busy={busy} disabled={s.unresolved > 0} onClick={() => act(() => api.post<GstRun>(`${url}/sign-off/`), setRun)}>
                  Sign off
                </Button>
              )}
              {s.unresolved > 0 && !locked && <span className="muted">{s.unresolved} row(s) still need a decision before sign-off.</span>}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function FileButton({ label, accept, onFile, busy }: { label: string; accept: string; onFile: (file: File) => void; busy: boolean }) {
  return (
    <label className={busy ? 'btn btn-default disabled' : 'btn btn-default'}>
      {label}
      <input
        type="file"
        accept={accept}
        hidden
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFile(file)
          e.target.value = ''
        }}
      />
    </label>
  )
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'warn' }) {
  return (
    <div className={tone ? `tile tile-${tone}` : 'tile'}>
      <div className="tile-label">{label}</div>
      <div className="tile-value money">{value}</div>
    </div>
  )
}

function Group({ group, canDecide, onDecide }: { group: GstGroup; canDecide: boolean; onDecide: (match: string, kind: string, note: string) => void }) {
  const [open, setOpen] = useState(group.kind !== 'matched')
  return (
    <div className="subpanel">
      <h3 onClick={() => setOpen(!open)} style={{ cursor: 'pointer' }}>
        {open ? '▾' : '▸'} {group.title} <Badge>{group.count}</Badge>
      </h3>
      {open && (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Invoice</th>
                <th>Date</th>
                <th className="num">Our tax</th>
                <th className="num">GSTR-2B tax</th>
                <th className="num">Eligible ITC</th>
                <th>Why</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((r) => (
                <Row key={r.id} row={r} kind={group.kind} canDecide={canDecide} onDecide={onDecide} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const tax = (x: GstMatchRow['book']) => (x ? formatPaise(x.igst_paise + x.cgst_paise + x.sgst_paise + x.cess_paise) : '—')

function Row({ row, kind, canDecide, onDecide }: { row: GstMatchRow; kind: string; canDecide: boolean; onDecide: (match: string, kind: string, note: string) => void }) {
  const ref = row.book ?? row.portal
  return (
    <tr>
      <td>
        {ref?.supplier_name || '—'}
        <div className="mono muted">{ref?.gstin || 'no GSTIN'}</div>
      </td>
      <td>
        {ref?.invoice_no}
        {row.portal && row.book && row.portal.invoice_no !== row.book.invoice_no && <div className="muted">2B: {row.portal.invoice_no}</div>}
      </td>
      <td>{formatDate(ref?.invoice_date)}</td>
      <td className="num money">{tax(row.book)}</td>
      <td className="num money">{tax(row.portal)}</td>
      <td className="num money">{formatPaise(row.eligible_paise)}</td>
      <td>
        {row.cause}
        {row.timing && <Badge tone="info">Timing</Badge>}
        {row.decision && (
          <div>
            <Badge tone="good">{row.decision.kind.replace('_', ' ')}</Badge>
          </div>
        )}
      </td>
      <td>
        {canDecide &&
          DECISIONS.filter((d) => d.for.includes(kind)).map((d) => (
            <Button key={d.kind} kind="ghost" className="btn-sm" onClick={() => onDecide(row.id, d.kind, '')}>
              {d.label}
            </Button>
          ))}
      </td>
    </tr>
  )
}

function Table4({ lines }: { lines: GstRun['gstr3b'] }) {
  return (
    <div className="subpanel">
      <h3>GSTR-3B Table 4 (indicative — verify against your ledgers before filing)</h3>
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th>Table</th>
              <th>Description</th>
              <th className="num">IGST</th>
              <th className="num">CGST</th>
              <th className="num">SGST</th>
              <th className="num">Cess</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.code}>
                <td className="mono">{l.code}</td>
                <td>{l.label}</td>
                <td className="num money">{formatPaise(l.igst_paise)}</td>
                <td className="num money">{formatPaise(l.cgst_paise)}</td>
                <td className="num money">{formatPaise(l.sgst_paise)}</td>
                <td className="num money">{formatPaise(l.cess_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
